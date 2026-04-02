"""Cliente InfluxDB para telemetria e series temporais do Plantelligence.

Dependencia: influxdb-client[async]  (adicionar ao requirements.txt quando integrar)
Variaveis de ambiente: INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET
"""

from __future__ import annotations

from app.config.settings import settings


class InfluxDB:
    """Wrapper async sobre InfluxDBClientAsync."""

    def __init__(self) -> None:
        """Inicializa o cliente como desconectado."""
        self._client = None

    async def connect(self) -> None:
        """Cria a conexao com InfluxDB usando variaveis de ambiente."""
        try:
            from influxdb_client_async import InfluxDBClientAsync  # type: ignore[import]
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
        """Fecha a conexao ativa com InfluxDB, se existir."""
        if self._client:
            await self._client.close()
            self._client = None

    async def write_point(self, point) -> None:
        """Escreve um ponto de telemetria no bucket configurado."""
        if self._client is None:
            raise RuntimeError("InfluxDB nao conectado. Chame connect() primeiro.")
        await self._client.write_api().write(bucket=settings.influx_bucket, record=point)

    async def query(self, query: str):
        """Executa consulta Flux e retorna os registros."""
        if self._client is None:
            raise RuntimeError("InfluxDB nao conectado. Chame connect() primeiro.")
        return await self._client.query_api().query(query=query)


influx_db = InfluxDB()
