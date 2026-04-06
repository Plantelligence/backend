"""Servicos de endereco para consulta de CEP via ViaCEP com cache em memoria."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock

import httpx


_VIACEP_URL = "https://viacep.com.br/ws/{cep}/json/"
_VIACEP_CACHE_TTL_SECONDS = 60 * 60
_viacep_cache: dict[str, tuple[datetime, dict[str, str]]] = {}
_viacep_cache_lock = Lock()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def mask_cep(cep: str) -> str:
    """Mascara o CEP para logs sem expor o valor completo."""
    digits = "".join(ch for ch in (cep or "") if ch.isdigit())
    if len(digits) < 8:
        return "***"
    return f"{digits[:5]}***"


def normalize_cep(cep: str) -> str:
    """Normaliza CEP removendo caracteres nao numericos e valida formato."""
    digits = "".join(ch for ch in (cep or "") if ch.isdigit())
    if len(digits) != 8:
        raise ValueError("CEP invalido. Informe exatamente 8 digitos numericos.")
    return digits


def _get_cached_location(cep: str) -> dict[str, str] | None:
    with _viacep_cache_lock:
        cached = _viacep_cache.get(cep)
        if not cached:
            return None

        expires_at, payload = cached
        if expires_at <= _now_utc():
            _viacep_cache.pop(cep, None)
            return None
        return payload


def _set_cached_location(cep: str, payload: dict[str, str]) -> None:
    with _viacep_cache_lock:
        _viacep_cache[cep] = (_now_utc() + timedelta(seconds=_VIACEP_CACHE_TTL_SECONDS), payload)


def resolve_cep_location(cep: str) -> dict[str, str]:
    """Consulta ViaCEP e retorna cidade/estado para o CEP informado."""
    normalized = normalize_cep(cep)

    cached = _get_cached_location(normalized)
    if cached:
        return cached

    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.get(_VIACEP_URL.format(cep=normalized))
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Falha na consulta ViaCEP (status {exc.response.status_code}).") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError("Falha de comunicacao com a API ViaCEP.") from exc

    if payload.get("erro") is True:
        raise LookupError("CEP inexistente na base ViaCEP.")

    cidade = (payload.get("localidade") or "").strip()
    estado = (payload.get("uf") or "").strip().upper()
    if not cidade or len(estado) != 2:
        raise RuntimeError("ViaCEP retornou dados incompletos para o CEP informado.")

    location = {
        "cep": normalized,
        "cidade": cidade,
        "estado": estado,
    }
    _set_cached_location(normalized, location)
    return location
