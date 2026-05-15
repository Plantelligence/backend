"""
Consumidor de telemetria do Azure IoT Hub (endpoint compatível com EventHub).

Quando o ESP32 envia dados dos sensores via MQTT, eles chegam ao Azure IoT Hub.
Este módulo fica "escutando" continuamente essas mensagens em background e,
para cada mensagem recebida, salva os dados no InfluxDB (banco de séries temporais).

O processo funciona assim:
  1. O ESP32 publica JSON com leituras dos sensores no tópico MQTT do IoT Hub;
  2. O IoT Hub encaminha as mensagens para o endpoint EventHub;
  3. Este consumidor lê as mensagens do EventHub e grava no InfluxDB;
  4. O dashboard do Plantelligence consulta o InfluxDB para exibir os gráficos.

Este consumidor é iniciado automaticamente no startup do FastAPI como uma
tarefa assíncrona (asyncio task) que roda em paralelo com o servidor HTTP.

Campos esperados no JSON enviado pelo ESP32:
  temperatura      (número, °C)    — leitura do sensor DHT11
  umidade          (número, %)     — leitura do sensor DHT11
  umidade_solo     (número, %)     — leitura do sensor de umidade do solo
  luminosidade     (número, lux)   — leitura do sensor LDR
  estufa_id        (texto)         — ID da estufa (opcional se enviado via propriedade)

Variações aceitas (retrocompatibilidade com nomes em inglês):
  temperature / humidity / soilMoisture / luminosity

Variáveis de ambiente necessárias:
  IOTHUB_EVENTHUB_ENDPOINT   — connection string do endpoint EventHub do IoT Hub
  IOTHUB_EVENTHUB_NAME       — nome do hub de eventos (geralmente o nome do IoT Hub)
  IOTHUB_CONSUMER_GROUP      — grupo de consumidores (padrão: $Default)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.config.settings import settings

logger = logging.getLogger(__name__)

# referência global para a task de background — usada para cancelamento futuro se necessário
_consumer_task: Optional[asyncio.Task] = None


def _parse_body(event) -> dict | None:
    """
    Tenta decodificar o corpo da mensagem IoT Hub como JSON.
    Retorna o dicionário com os dados ou None se não for JSON válido.
    """
    try:
        raw = event.body_as_str(encoding="utf-8")
        return json.loads(raw)
    except Exception:
        return None


def _extract_estufa_id(data: dict, event) -> str | None:
    """
    Extrai o ID da estufa da mensagem, tentando três fontes diferentes:
      1. Campo 'estufa_id' ou 'estufaId' no corpo JSON;
      2. Propriedade 'estufa_id' nos metadados da mensagem (application properties);
      3. ID do dispositivo no sistema IoT Hub (iothub-connection-device-id).

    A fonte 3 serve como fallback para dispositivos que não enviam o estufa_id
    explicitamente — nesses casos, usa-se o device ID como identificador.
    """
    # 1) campo no corpo JSON
    estufa_id = data.get("estufa_id") or data.get("estufaId")
    if estufa_id:
        return str(estufa_id)

    # 2) propriedade da mensagem (metadados enviados junto com o payload)
    try:
        props = event.properties or {}
        val = props.get("estufa_id") or props.get(b"estufa_id")
        if val:
            return val.decode("utf-8", errors="ignore") if isinstance(val, bytes) else str(val)
    except Exception:
        pass

    # 3) device ID do sistema IoT Hub (iothub-connection-device-id)
    try:
        sys_props = event.system_properties or {}
        device_id = sys_props.get("iothub-connection-device-id")
        if device_id:
            return device_id.decode("utf-8", errors="ignore") if isinstance(device_id, bytes) else str(device_id)
    except Exception:
        pass

    return None


def _extract_float(data: dict, *keys) -> float | None:
    """
    Tenta extrair um valor numérico do dicionário usando uma lista de chaves alternativas.
    Retorna o primeiro valor encontrado e convertível para float, ou None se não encontrar.
    """
    for key in keys:
        val = data.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


async def _on_event(partition_context, event) -> None:
    """
    Callback chamado para cada mensagem recebida do Azure IoT Hub.

    Etapas:
      1. Decodifica o corpo JSON da mensagem;
      2. Extrai o ID da estufa de destino;
      3. Lê os valores dos 4 sensores (com suporte a nomes em PT e EN);
      4. Salva no InfluxDB com o timestamp da mensagem (ou o momento atual);
      5. Confirma o processamento da mensagem (checkpoint) para não reprocessar.
    """
    from app.db.influx.influx import influx_db

    try:
        data = _parse_body(event)
        if not data or not isinstance(data, dict):
            return

        estufa_id = _extract_estufa_id(data, event)
        if not estufa_id:
            logger.debug("Mensagem IoT Hub sem estufa_id — ignorada.")
            return

        # extrai os valores dos sensores aceitando nomes em português e inglês
        temperatura  = _extract_float(data, "temperatura", "temperature")
        umidade      = _extract_float(data, "umidade", "humidity")
        umidade_solo = _extract_float(data, "umidade_solo", "soilMoisture", "soil_moisture")
        luminosidade = _extract_float(data, "luminosidade", "luminosity")

        # usa o timestamp da mensagem no IoT Hub quando disponível (mais preciso)
        ts: datetime | None = None
        try:
            enqueued = event.enqueued_time
            if enqueued:
                ts = enqueued if enqueued.tzinfo else enqueued.replace(tzinfo=timezone.utc)
        except Exception:
            pass

        await influx_db.write_telemetry(
            estufa_id=estufa_id,
            temperatura=temperatura,
            umidade=umidade,
            umidade_solo=umidade_solo,
            luminosidade=luminosidade,
            timestamp=ts,
        )

        # confirma que esta mensagem foi processada (evita reprocessamento em caso de reinício)
        await partition_context.update_checkpoint(event)

    except Exception as exc:
        logger.warning("Erro ao processar mensagem IoT Hub: %s", exc)


async def _run_consumer() -> None:
    """
    Loop principal do consumidor: conecta ao EventHub do IoT Hub e fica ouvindo
    mensagens indefinidamente. Em caso de falha na conexão, reconecta automaticamente
    com espera progressiva (10s → 20s → 40s → máximo 120s entre tentativas).
    """
    if not settings.iothub_eventhub_endpoint or not settings.iothub_eventhub_name:
        logger.info(
            "IoT Hub não configurado (IOTHUB_EVENTHUB_ENDPOINT / IOTHUB_EVENTHUB_NAME ausentes). "
            "Consumer não iniciado."
        )
        return

    try:
        from azure.eventhub.aio import EventHubConsumerClient  # type: ignore[import]
    except ImportError:
        logger.warning("azure-eventhub não instalado. Consumer IoT Hub não iniciado.")
        return

    retry_delay = 10  # tempo de espera inicial entre tentativas de reconexão (segundos)
    while True:
        try:
            logger.info(
                "[iothub] Iniciando consumer: hub=%s grupo=%s",
                settings.iothub_eventhub_name,
                settings.iothub_consumer_group,
            )
            client = EventHubConsumerClient.from_connection_string(
                conn_str=settings.iothub_eventhub_endpoint,
                consumer_group=settings.iothub_consumer_group,
                eventhub_name=settings.iothub_eventhub_name,
            )
            async with client:
                # @latest = processa apenas mensagens novas (chegadas após a conexão)
                # para não reprocessar histórico antigo toda vez que o servidor reinicia
                await client.receive(
                    on_event=_on_event,
                    starting_position="@latest",
                )
            # se receive() retornar sem erro, reconecta imediatamente
            retry_delay = 10
        except asyncio.CancelledError:
            logger.info("[iothub] Consumer cancelado.")
            return
        except Exception as exc:
            logger.error(
                "[iothub] Consumer parou (%s). Reconectando em %ds...", exc, retry_delay
            )
            await asyncio.sleep(retry_delay)
            # dobra o tempo de espera a cada falha consecutiva, até o máximo de 2 minutos
            retry_delay = min(retry_delay * 2, 120)


def start_iothub_consumer() -> asyncio.Task:
    """
    Inicia o consumidor IoT Hub como uma tarefa assíncrona em background.
    Deve ser chamada uma única vez durante o startup do FastAPI.
    A tarefa continua rodando enquanto o servidor estiver ativo.
    """
    global _consumer_task
    _consumer_task = asyncio.create_task(_run_consumer(), name="iothub-consumer")
    return _consumer_task
