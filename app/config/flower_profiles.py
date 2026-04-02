"""Perfis de cultivo de cogumelos usados na avaliacao de metricas de estufa."""

# Cada perfil define as faixas ideais de temperatura, umidade relativa e umidade
# do substrato para uma especie de cogumelo. O avaliador de metricas compara
# as leituras dos sensores IoT com esses valores e dispara alertas quando necessario.

from __future__ import annotations

from typing import Any

# Banco de perfis de cultivo — adicione novas especies aqui conforme necessario.
# Os IDs precisam ser strings simples (slug) porque o frontend os usa como chave.
flower_profiles: list[dict[str, Any]] = [
    {
        "id": "champignon",
        "name": "Champignon",
        "summary": "Agaricus bisporus em ambiente fresco com alta umidade e substrato rico em composto organico.",
        "temperature": {"min": 15, "max": 20},
        "humidity": {"min": 80, "max": 90},
        "soilMoisture": {"min": 60, "max": 75},
    },
    {
        "id": "shimeji",
        "name": "Shimeji",
        "summary": "Pleurotus sp. cultivado em toras ou serragem de eucalipto, exige boa ventilacao e umidade elevada.",
        "temperature": {"min": 20, "max": 25},
        "humidity": {"min": 80, "max": 90},
        "soilMoisture": {"min": 55, "max": 70},
    },
    {
        "id": "shiitake",
        "name": "Shiitake",
        "summary": "Lentinula edodes em toras de eucalipto ou blocos de serragem enriquecida, sabor defumado intenso.",
        "temperature": {"min": 18, "max": 25},
        "humidity": {"min": 75, "max": 90},
        "soilMoisture": {"min": 55, "max": 70},
    },
    {
        "id": "ostra",
        "name": "Cogumelo Ostra",
        "summary": "Pleurotus ostreatus de crescimento rapido em palha de trigo ou serragem, alta umidade do ar.",
        "temperature": {"min": 18, "max": 26},
        "humidity": {"min": 85, "max": 95},
        "soilMoisture": {"min": 60, "max": 75},
    },
    {
        "id": "portobello",
        "name": "Portobello",
        "summary": "Variante do Agaricus bisporus com cogumelo grande e sabor intenso, ciclo mais longo que o champignon.",
        "temperature": {"min": 14, "max": 20},
        "humidity": {"min": 75, "max": 90},
        "soilMoisture": {"min": 60, "max": 75},
    },
]


def find_flower_profile(profile_id: str | None) -> dict[str, Any] | None:
    """Busca um perfil de cultivo pelo identificador (slug)."""

    if not profile_id:
        return None
    return next((profile for profile in flower_profiles if profile["id"] == profile_id), None)
