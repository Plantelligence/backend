"""
Servico de envio de comandos a dispositivos via Azure IoT Hub.

Dois metodos de entrega sao suportados:

1. Cloud-to-Device (C2D) Messages
   - Mensagem enfileirada no IoT Hub (ate 50 mensagens por dispositivo)
   - Dispositivo recebe quando se conecta e faz pull
   - Sem resposta sincrona — "fire and forget"
   - Ideal para comandos que nao precisam de confirmacao imediata

2. Direct Methods
   - Chamada sincrona ao dispositivo (requer dispositivo online)
   - Dispositivo responde com status code + payload em ate N segundos
   - Ideal para comandos que precisam de confirmacao (ex.: ligar/desligar)

Fluxo de envio:
  1. Frontend envia comando via API REST
  2. Backend valida permissao do usuario e existencia do dispositivo
  3. Backend registra o comando no historico (status = pending)
  4. Backend envia ao IoT Hub (C2D ou Direct Method)
  5. Backend atualiza o historico (status = sent/delivered/failed)

O ESP32 deve estar configurado para:
  - C2D: receber mensagens no callback de cloud-to-device
  - Direct Method: registrar handlers para metodos como "ligar", "desligar", "ajustar"
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.config.settings import settings

logger = logging.getLogger(__name__)


class IoTCommandService:
    """
    Servico responsavel por enviar comandos a dispositivos registrados
    no Azure IoT Hub via Cloud-to-Device messages ou Direct Methods.
    """

    def __init__(self) -> None:
        self._connection_string = (settings.iothub_connection_string or "").strip()
        if not self._connection_string:
            raise RuntimeError(
                "IoT Hub nao configurado: IOTHUB_CONNECTION_STRING ausente. "
                "Comandos a atuadores nao podem ser enviados sem o IoT Hub."
            )

    # ── Cloud-to-Device Messages (assincrono, sem resposta) ───────────────────

    async def send_c2d_message(
        self,
        device_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Envia uma mensagem Cloud-to-Device ao dispositivo.

        A mensagem e enfileirada no IoT Hub e sera entregue quando o dispositivo
        se conectar e fizer pull. O IoT Hub armazena ate 50 mensagens por dispositivo.

        Retorna:
          {"messageId": "...", "status": "sent"}

        Lanca Exception se o envio falhar.
        """
        try:
            from azure.iot.hub import IoTHubRegistryManager  # type: ignore[import]
            from azure.iot.hub.models import Message  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                "azure-iot-hub nao esta instalado. "
                "Execute: pip install azure-iot-hub"
            )

        message = Message(json.dumps(payload))
        message.content_type = "application/json"
        message.content_encoding = "utf-8"
        # propriedades customizadas para o dispositivo identificar o tipo
        message.custom_properties["command_type"] = payload.get("command", "custom")
        message.custom_properties["sent_at"] = datetime.now(timezone.utc).isoformat()

        registry_manager = IoTHubRegistryManager(self._connection_string)
        sent_message = registry_manager.send_c2d_message(device_id, message)

        logger.info(
            "c2d_message_sent device_id=%s message_id=%s command=%s",
            device_id,
            sent_message.message_id,
            payload.get("command", "custom"),
        )

        return {
            "messageId": sent_message.message_id,
            "status": "sent",
        }

    # ── Direct Methods (sincrono, com resposta do dispositivo) ────────────────

    async def invoke_direct_method(
        self,
        device_id: str,
        method_name: str,
        payload: dict[str, Any] | None = None,
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        """
        Invoca um metodo direto no dispositivo e aguarda resposta.

        O dispositivo deve ter um handler registrado para `method_name`.
        Se o dispositivo nao estiver online, o IoT Hub retorna erro apos o timeout.

        Retorna:
          {
            "status": 200,
            "payload": {...},       # resposta do dispositivo
            "methodRequestId": "..."
          }

        Lanca Exception se o dispositivo nao responder ou o metodo nao existir.
        """
        try:
            from azure.iot.hub import IoTHubRegistryManager  # type: ignore[import]
            from azure.iot.hub.models import CloudToDeviceMethod  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                "azure-iot-hub nao esta instalado. "
                "Execute: pip install azure-iot-hub"
            )

        c2d_method = CloudToDeviceMethod(
            method_name=method_name,
            payload=json.dumps(payload) if payload else None,
            response_timeout_in_seconds=timeout_seconds,
            connect_timeout_in_seconds=5,
        )

        registry_manager = IoTHubRegistryManager(self._connection_string)
        result = registry_manager.invoke_device_method(device_id, c2d_method)

        # parse da resposta do dispositivo
        response_payload = {}
        if result.payload:
            try:
                response_payload = json.loads(result.payload) if isinstance(result.payload, str) else result.payload
            except (json.JSONDecodeError, TypeError):
                response_payload = {"raw": str(result.payload)}

        logger.info(
            "direct_method_invoked device_id=%s method=%s status=%s",
            device_id,
            method_name,
            result.status,
        )

        return {
            "status": result.status,
            "payload": response_payload,
            "methodRequestId": result.request_id if hasattr(result, "request_id") else None,
        }

    # ── Consulta de status do dispositivo ─────────────────────────────────────

    async def get_device_twin(self, device_id: str) -> dict[str, Any]:
        """
        Retorna o device twin (estado desejado + relatado) do dispositivo.

        O device twin contem:
          - properties.desired: configuracoes que o sistema quer que o dispositivo aplique
          - properties.reported: estado atual relatado pelo dispositivo
          - connectionState: "Connected" ou "Disconnected"
          - lastActivityTime: ultima vez que o dispositivo se comunicou

        Usado para verificar se o dispositivo esta online e qual seu estado atual.
        """
        try:
            from azure.iot.hub import IoTHubRegistryManager  # type: ignore[import]
        except ImportError:
            raise RuntimeError("azure-iot-hub nao esta instalado.")

        registry_manager = IoTHubRegistryManager(self._connection_string)
        twin = registry_manager.get_twin(device_id)

        return {
            "deviceId": twin.device_id,
            "connectionState": twin.connection_state,
            "lastActivityTime": twin.last_activity_time.isoformat() if twin.last_activity_time else None,
            "status": twin.status,
            "statusUpdateTime": twin.status_updated_time.isoformat() if twin.status_updated_time else None,
            "desiredProperties": twin.properties.desired if twin.properties else {},
            "reportedProperties": twin.properties.reported if twin.properties else {},
        }

    # ── Atualizar desired properties do twin ──────────────────────────────────

    async def update_twin_desired_properties(
        self,
        device_id: str,
        desired: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Atualiza as propriedades desejadas (desired) do device twin.

        O dispositivo recebe uma notificacao quando as desired properties mudam
        e pode aplicar as novas configuracoes. E o metodo recomendado para
        enviar configuracoes persistentes ao dispositivo.

        Exemplo: {"ventilation": {"enabled": true, "speed": 80}}
        """
        try:
            from azure.iot.hub import IoTHubRegistryManager  # type: ignore[import]
        except ImportError:
            raise RuntimeError("azure-iot-hub nao esta instalado.")

        registry_manager = IoTHubRegistryManager(self._connection_string)
        twin = registry_manager.get_twin(device_id)

        # mescla com desired properties existentes (patch parcial)
        existing = twin.properties.desired if twin.properties else {}
        merged = _deep_merge(existing, desired)

        patch = {"properties": {"desired": merged}}
        updated_twin = registry_manager.update_twin(device_id, patch, twin.etag)

        logger.info(
            "twin_updated device_id=%s desired_keys=%s",
            device_id,
            list(desired.keys()),
        )

        return {
            "deviceId": updated_twin.device_id,
            "etag": updated_twin.etag,
            "desiredProperties": updated_twin.properties.desired if updated_twin.properties else {},
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: IoTCommandService | None = None


def get_command_service() -> IoTCommandService:
    """Retorna a instancia unica do servico de comandos."""
    global _instance
    if _instance is None:
        _instance = IoTCommandService()
    return _instance


# ── Utilitarios ───────────────────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """Mescla dois dicionarios recursivamente (override tem prioridade)."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def build_actuator_payload(
    command_type: str,
    payload: dict | None = None,
) -> dict[str, Any]:
    """
    Constroi o payload padronizado enviado ao atuador.

    Formato esperado pelo firmware ESP32:
      {
        "command": "ligar" | "desligar" | "ajustar" | "custom",
        "parameter": "intensidade" | "vazao" | ... (opcional),
        "value": 70.0 (opcional),
        "unit": "%" (opcional),
        "timestamp": "2025-01-15T10:30:00Z"
      }
    """
    result: dict[str, Any] = {
        "command": command_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if command_type == "ajustar" and payload:
        result["parameter"] = payload.get("parameter", "")
        result["value"] = payload.get("value")
        result["unit"] = payload.get("unit")
    elif command_type == "custom" and payload:
        result.update(payload)

    return result
