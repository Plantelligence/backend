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
        "summary": "Agaricus bisporus (fase de frutificacao) em ambiente fresco, alta umidade e boa renovacao de ar.",
        "temperature": {"min": 15, "max": 19},
        "humidity": {"min": 88, "max": 95},
        "soilMoisture": {"min": 60, "max": 68},
    },
    {
        "id": "shimeji",
        "name": "Shimeji",
        "summary": "Shimeji (Hypsizygus tessellatus) em substrato de serragem enriquecida, com ambiente fresco e umido.",
        "temperature": {"min": 14, "max": 18},
        "humidity": {"min": 85, "max": 92},
        "soilMoisture": {"min": 58, "max": 66},
    },
    {
        "id": "shiitake",
        "name": "Shiitake",
        "summary": "Lentinula edodes em toras/blocos, com choque termico para frutificacao e alta umidade relativa.",
        "temperature": {"min": 12, "max": 18},
        "humidity": {"min": 85, "max": 95},
        "soilMoisture": {"min": 58, "max": 68},
    },
]


def find_flower_profile(profile_id: str | None) -> dict[str, Any] | None:
    """Busca um perfil de cultivo pelo identificador (slug)."""

    if not profile_id:
        return None
    return next((profile for profile in flower_profiles if profile["id"] == profile_id), None)
