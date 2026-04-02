"""Servico de previsao do tempo para estufas com base na OpenWeatherMap API."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import httpx

from app.config.settings import settings
from app.schemas.previsao_dia import PrevisaoDia
from app.schemas.alertas_clima import Clima, ClimaTipo
from app.schemas.clima_resposta import ClimaResposta


# URL base da API de previsão do OpenWeatherMap (previsão de 5 dias, intervalo de 3h)
_OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"


async def _buscar_dados_api(cidade: str, estado: str) -> dict:
    """Busca previsao bruta na API externa em celsius e idioma pt-BR."""
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

    async with httpx.AsyncClient() as client:
        response = await client.get(_OWM_FORECAST_URL, params=params, timeout=10.0)
        response.raise_for_status()
        return response.json()


def _agrupar_por_dia(data: dict) -> dict[str, list[dict]]:
    """Agrupa as medicoes de 3h por data para montar o resumo diario."""
    dias: dict[str, list[dict]] = defaultdict(list)
    for entrada in data.get("list", []):
        data_str = entrada["dt_txt"].split(" ")[0]
        dias[data_str].append(entrada)
    return dict(dias)


def _calcular_previsao_dia(data_str: str, medicoes: list[dict], estufa_id: str) -> PrevisaoDia:
    """Calcula minimo/maximo diario a partir das medicoes da API."""
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
    """Converte previsoes diarias em alertas climaticos acionaveis."""
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
    """Fluxo principal de previsao: coleta, agrega, avalia e retorna resposta final."""
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
