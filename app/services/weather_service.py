# previsão do tempo via OpenWeatherMap para as estufas

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from threading import Lock

import httpx

from app.config.settings import settings
from app.schemas.previsao_dia import PrevisaoDia
from app.schemas.alertas_clima import Clima, ClimaTipo
from app.schemas.clima_resposta import ClimaResposta


# previsão de 5 dias em blocos de 3h
_OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
_OWM_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
_FORECAST_CACHE_TTL_SECONDS = 10 * 60
_CURRENT_CACHE_TTL_SECONDS = 5 * 60

_forecast_cache: dict[str, tuple[datetime, dict]] = {}
_current_cache: dict[str, tuple[datetime, dict]] = {}
_cache_lock = Lock()


def _cache_key(cidade: str, estado: str) -> str:
    return f"{(cidade or '').strip().lower()}::{(estado or '').strip().upper()}"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _cache_get(cache: dict[str, tuple[datetime, dict]], key: str) -> dict | None:
    with _cache_lock:
        item = cache.get(key)
        if not item:
            return None

        expires_at, payload = item
        if expires_at <= _now_utc():
            cache.pop(key, None)
            return None

        return payload


def _cache_set(cache: dict[str, tuple[datetime, dict]], key: str, payload: dict, ttl_seconds: int) -> None:
    with _cache_lock:
        cache[key] = (_now_utc() + timedelta(seconds=ttl_seconds), payload)


async def _buscar_dados_api(cidade: str, estado: str) -> dict:
    if not settings.openweathermap_api_key:
        raise RuntimeError(
            "OPENWEATHERMAP_API_KEY nao configurada. "
            "Adicione a chave no seu arquivo .env."
        )

    params = {
        "q": f"{cidade},{estado},BR",
        "appid": settings.openweathermap_api_key,
        "units": "metric",
        "lang": "pt_br",
    }

    key = _cache_key(cidade, estado)
    cached = _cache_get(_forecast_cache, key)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(_OWM_FORECAST_URL, params=params, timeout=10.0)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise ValueError(f"Cidade/UF nao encontrada na OpenWeather: {cidade}/{estado}.") from exc
        raise RuntimeError(f"Falha na OpenWeather (status {exc.response.status_code}).") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError("Falha de comunicacao com a OpenWeather.") from exc

    _cache_set(_forecast_cache, key, payload, _FORECAST_CACHE_TTL_SECONDS)
    return payload


async def buscar_clima_externo_atual(cidade: str, estado: str) -> dict:
    if not settings.openweathermap_api_key:
        raise RuntimeError(
            "OPENWEATHERMAP_API_KEY nao configurada. "
            "Adicione a chave no seu arquivo .env."
        )

    normalized_city = (cidade or "").strip()
    normalized_state = (estado or "").strip().upper()
    if not normalized_city or len(normalized_state) != 2:
        raise ValueError("Cidade/estado invalidos para consulta climatica externa.")

    key = _cache_key(normalized_city, normalized_state)
    cached = _cache_get(_current_cache, key)
    if cached:
        return cached

    params = {
        "q": f"{normalized_city},{normalized_state},BR",
        "appid": settings.openweathermap_api_key,
        "units": "metric",
        "lang": "pt_br",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(_OWM_CURRENT_URL, params=params, timeout=10.0)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise ValueError(f"Cidade/UF nao encontrada na OpenWeather: {normalized_city}/{normalized_state}.") from exc
        raise RuntimeError(f"Falha na OpenWeather (status {exc.response.status_code}).") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError("Falha de comunicacao com a OpenWeather.") from exc

    weather_info = (payload.get("weather") or [{}])[0]
    main_data = payload.get("main") or {}
    raw_temp = main_data.get("temp")
    raw_humidity = main_data.get("humidity")

    if raw_temp is None or raw_humidity is None:
        raise RuntimeError("OpenWeather retornou dados incompletos de temperatura/umidade.")

    current = {
        "cidade": normalized_city,
        "estado": normalized_state,
        "temperatura": round(float(raw_temp), 1),
        "umidade": int(raw_humidity),
        "descricao": weather_info.get("description") or "sem descricao",
        "condicao": weather_info.get("main") or "Desconhecida",
        "atualizado_em": _now_utc(),
    }

    _cache_set(_current_cache, key, current, _CURRENT_CACHE_TTL_SECONDS)
    return current


def _agrupar_por_dia(data: dict) -> dict[str, list[dict]]:
    dias: dict[str, list[dict]] = defaultdict(list)
    for entrada in data.get("list", []):
        data_str = entrada["dt_txt"].split(" ")[0]
        dias[data_str].append(entrada)
    return dict(dias)


def _calcular_previsao_dia(data_str: str, medicoes: list[dict], estufa_id: str) -> PrevisaoDia:
    temperaturas = [m["main"]["temp"] for m in medicoes]
    umidades = [m["main"]["humidity"] for m in medicoes]
    chances_chuva = [m.get("pop", 0) * 100 for m in medicoes]
    ventos = [m["wind"]["speed"] * 3.6 for m in medicoes]

    return PrevisaoDia(
        data=datetime.strptime(data_str, "%Y-%m-%d").date(),
        temperatura_min=round(min(temperaturas), 1),
        temperatura_max=round(max(temperaturas), 1),
        umidade_min=round(min(umidades), 1),
        umidade_max=round(max(umidades), 1),
        chance_chuva=round(max(chances_chuva), 1),
        velocidade_vento=round(max(ventos), 1),
        estufa_id=estufa_id,
        gerado_em=datetime.now(timezone.utc),
    )


def _gerar_alertas(previsoes: list[PrevisaoDia], estufa_id: str) -> list[Clima]:
    alertas: list[Clima] = []
    agora = datetime.now(timezone.utc)

    for previsao in previsoes:
        if previsao.temperatura_max >= 35.0:
            alertas.append(Clima(
                tipo=ClimaTipo.onda_calor,
                descricao=f"Temperatura maxima de {previsao.temperatura_max}°C prevista para {previsao.data}.",
                recomendacao="Reforce a ventilacao e verifique o sistema de refrigeracao da estufa.",
                estufa_id=estufa_id,
                gerado_em=agora,
            ))

        if previsao.temperatura_min <= 5.0:
            alertas.append(Clima(
                tipo=ClimaTipo.geada,
                descricao=f"Temperatura minima de {previsao.temperatura_min}°C prevista para {previsao.data}.",
                recomendacao="Ative o aquecimento e proteja os substratos contra o frio extremo.",
                estufa_id=estufa_id,
                gerado_em=agora,
            ))

        if previsao.chance_chuva >= 70.0:
            alertas.append(Clima(
                tipo=ClimaTipo.tempestade,
                descricao=f"Chance de chuva de {previsao.chance_chuva}% prevista para {previsao.data}.",
                recomendacao="Verifique a vedacao da estufa e os sistemas de drenagem.",
                estufa_id=estufa_id,
                gerado_em=agora,
            ))

        if previsao.velocidade_vento >= 60.0:
            alertas.append(Clima(
                tipo=ClimaTipo.vento_forte,
                descricao=f"Vento de ate {previsao.velocidade_vento} km/h previsto para {previsao.data}.",
                recomendacao="Fixe estruturas expostas e verifique a integridade da cobertura.",
                estufa_id=estufa_id,
                gerado_em=agora,
            ))

    return alertas


async def buscar_clima_estufa(cidade: str, estado: str, estufa_id: str) -> ClimaResposta:
    dados = await _buscar_dados_api(cidade, estado)

    dias = _agrupar_por_dia(dados)
    if not dias:
        raise ValueError(f"Nenhuma previsao disponivel para {cidade}/{estado}.")

    previsoes = [
        _calcular_previsao_dia(data_str, medicoes, estufa_id)
        for data_str, medicoes in sorted(dias.items())
    ]

    alertas = _gerar_alertas(previsoes, estufa_id)

    return ClimaResposta(previsao=previsoes, alertas=alertas)
