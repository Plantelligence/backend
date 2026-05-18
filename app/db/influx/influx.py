"""
Cliente InfluxDB para armazenamento e consulta de dados de telemetria.

O InfluxDB é um banco de dados especializado em séries temporais — ou seja,
dados que mudam ao longo do tempo, como temperatura, umidade e luminosidade.
Ele é mais eficiente que o PostgreSQL para armazenar e consultar leituras frequentes
de sensores porque é otimizado exatamente para esse tipo de dado.

Como os dados são organizados:
  - Measurement: "telemetria_estufa" (equivale a uma tabela no SQL)
  - Tag: estufa_id (identifica a qual estufa pertencem os dados)
  - Fields: temperatura, umidade, umidade_solo, luminosidade (os valores medidos)
  - Timestamp: data e hora exata da leitura

Para realizar consultas, usamos a linguagem Flux (própria do InfluxDB).

Variáveis de ambiente necessárias:
  INFLUX_URL    — endereço do servidor InfluxDB (ex.: http://localhost:8086)
  INFLUX_TOKEN  — token de autenticação
  INFLUX_ORG    — organização configurada no InfluxDB
  INFLUX_BUCKET — nome do bucket onde os dados são armazenados (ex.: telemetria)
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Optional

from app.config.settings import settings

logger = logging.getLogger(__name__)

# nome do "measurement" — agrupa todos os dados de telemetria das estufas
_MEASUREMENT = "telemetria_estufa"

# regex para validar datas no formato YYYY-MM-DD antes de usar em queries
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class InfluxDB:
    """
    Wrapper assíncrono para o cliente InfluxDB.

    A conexão é criada sob demanda (lazy) na primeira operação de leitura ou escrita,
    usando um Lock para garantir que apenas uma conexão seja criada em cenários
    de múltiplas requisições simultâneas (concorrência).
    """

    def __init__(self) -> None:
        self._client = None
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        """Cria o Lock de concorrência na primeira vez que for necessário."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _ensure_connected(self) -> None:
        """Garante que a conexão com o InfluxDB está ativa antes de qualquer operação."""
        if self._client is not None:
            return
        async with self._get_lock():
            if self._client is not None:
                return
            await self.connect()

    async def connect(self) -> None:
        """
        Cria a conexão assíncrona com o InfluxDB.
        Lança RuntimeError se as variáveis de ambiente não estiverem configuradas
        ou se a biblioteca influxdb-client[async] não estiver instalada.
        """
        if not settings.influx_url or not settings.influx_token:
            raise RuntimeError("InfluxDB não configurado (INFLUX_URL / INFLUX_TOKEN ausentes).")
        try:
            from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "influxdb-client[async] nao esta instalado. "
                "Adicione 'influxdb-client[async]' ao requirements.txt."
            ) from exc

        self._client = InfluxDBClientAsync(
            url=settings.influx_url,
            token=settings.influx_token,
            org=settings.influx_org,
        )

    async def close(self) -> None:
        """Encerra a conexão com o InfluxDB de forma limpa (chamado no shutdown)."""
        if self._client:
            await self._client.close()
            self._client = None

    async def write_point(self, point) -> None:
        """Grava um ponto de dados (point) diretamente no bucket configurado."""
        await self._ensure_connected()
        await self._client.write_api().write(bucket=settings.influx_bucket, record=point)

    async def write_telemetry(
        self,
        *,
        estufa_id: str,
        temperatura: Optional[float] = None,
        umidade: Optional[float] = None,
        umidade_solo: Optional[float] = None,
        luminosidade: Optional[float] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Salva uma leitura dos sensores no InfluxDB.

        Apenas os campos com valor (não None) são gravados, o que permite
        que um sensor envie dados parciais sem problema.
        Se todos os campos forem None, a função retorna sem fazer nada.

        Parâmetros:
          estufa_id    — ID da estufa para identificar os dados na consulta
          temperatura  — temperatura do ar em graus Celsius
          umidade      — umidade relativa do ar em porcentagem
          umidade_solo — umidade do substrato/solo em porcentagem
          luminosidade — intensidade luminosa em lux
          timestamp    — data/hora da leitura (usa o horário atual se não informado)
        """
        # filtra os campos que têm valor para não gravar entradas vazias
        fields: dict = {}
        for name, val in [
            ("temperatura", temperatura),
            ("umidade", umidade),
            ("umidade_solo", umidade_solo),
            ("luminosidade", luminosidade),
        ]:
            if val is not None:
                try:
                    fields[name] = float(val)
                except (TypeError, ValueError):
                    pass

        if not fields:
            return

        try:
            from influxdb_client import Point  # type: ignore[import]
        except ImportError:
            logger.warning("influxdb-client não instalado. Telemetria descartada.")
            return

        # constrói o ponto de dados com a tag da estufa e os campos dos sensores
        point = Point(_MEASUREMENT).tag("estufa_id", estufa_id)
        for k, v in fields.items():
            point = point.field(k, v)
        if timestamp:
            point = point.time(timestamp)

        await self.write_point(point)

    async def query_sensor_averages(self, estufa_id: str, inicio: str, fim: str) -> dict:
        """
        Calcula e retorna as médias dos 4 sensores para um período de tempo.

        Usado para gerar relatórios — por exemplo, "qual foi a temperatura média
        desta estufa na última semana?".

        As datas devem estar no formato YYYY-MM-DD (ex.: "2025-01-15").
        Retorna um dicionário com as médias arredondadas em 2 casas decimais:
          { "temperatura": 22.5, "umidade": 87.3, "umidade_solo": 65.0, "luminosidade": 840.2 }

        Lança ValueError se as datas estiverem em formato inválido.
        """
        if not _DATE_RE.match(inicio) or not _DATE_RE.match(fim):
            raise ValueError("Formato de data inválido. Use YYYY-MM-DD.")

        # sanitiza o estufa_id para evitar injeção de código na query Flux
        safe_id = estufa_id.replace('"', "").replace("\\", "")

        # query Flux: filtra por estufa e período, agrupa por sensor e calcula a média
        query = (
            f'from(bucket: "{settings.influx_bucket}")\n'
            f'  |> range(start: {inicio}T00:00:00Z, stop: {fim}T23:59:59Z)\n'
            f'  |> filter(fn: (r) => r._measurement == "{_MEASUREMENT}")\n'
            f'  |> filter(fn: (r) => r.estufa_id == "{safe_id}")\n'
            '  |> filter(fn: (r) => r._field == "temperatura" or r._field == "umidade" '
            'or r._field == "umidade_solo" or r._field == "luminosidade")\n'
            '  |> group(columns: ["_field"])\n'
            '  |> mean()'
        )

        tables = await self.query(query)
        result: dict = {}
        for table in tables:
            for record in table.records:
                field = record.get_field()
                value = record.get_value()
                if value is not None:
                    result[field] = round(float(value), 2)
        return result

    async def query(self, query: str):
        """Executa uma query Flux genérica e retorna os resultados em tabelas."""
        await self._ensure_connected()
        return await self._client.query_api().query(query=query)

    async def query_sensor_averages_range(
        self,
        estufa_id: str,
        start: str,
        stop: str,
    ) -> dict:
        """
        Calcula as medias dos sensores para um intervalo ISO 8601.

        Diferente de query_sensor_averages (que usa YYYY-MM-DD), este metodo
        aceita timestamps completos no formato ISO 8601 (ex.: 2025-01-15T10:30:00Z).

        Usado pelos detectores automaticos para verificar metricas em janelas curtas.
        """
        safe_id = estufa_id.replace('"', "").replace("\\", "")

        query = (
            f'from(bucket: "{settings.influx_bucket}")\n'
            f'  |> range(start: {start}, stop: {stop})\n'
            f'  |> filter(fn: (r) => r._measurement == "{_MEASUREMENT}")\n'
            f'  |> filter(fn: (r) => r.estufa_id == "{safe_id}")\n'
            '  |> filter(fn: (r) => r._field == "temperatura" or r._field == "umidade" '
            'or r._field == "umidade_solo" or r._field == "luminosidade")\n'
            '  |> group(columns: ["_field"])\n'
            '  |> mean()'
        )

        try:
            tables = await self.query(query)
        except Exception:
            return {}

        result: dict = {}
        for table in tables:
            for record in table.records:
                field = record.get_field()
                value = record.get_value()
                if value is not None:
                    result[field] = round(float(value), 2)
        return result


# instância global compartilhada por todo o backend
# usada em: iothub_consumer.py, telemetria.py, relatorios.py
influx_db = InfluxDB()
