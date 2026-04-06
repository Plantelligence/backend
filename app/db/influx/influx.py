"""
Cliente InfluxDB para telemetria e séries temporais.

Requer: influxdb-client[async]
Env vars: INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET
"""

from __future__ import annotations

from app.config.settings import settings


class InfluxDB:
    def __init__(self) -> None:
        self._client = None

    async def connect(self) -> None:
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
        if self._client:
            await self._client.close()
            self._client = None

    async def write_point(self, point) -> None:
        if self._client is None:
            raise RuntimeError("InfluxDB nao conectado. Chame connect() primeiro.")
        await self._client.write_api().write(bucket=settings.influx_bucket, record=point)

    async def query(self, query: str):
        if self._client is None:
            raise RuntimeError("InfluxDB nao conectado. Chame connect() primeiro.")
        return await self._client.query_api().query(query=query)


influx_db = InfluxDB()
