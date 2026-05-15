"""
Rota HTTP para recepção direta de telemetria dos sensores.

Este endpoint permite que dados dos sensores sejam enviados diretamente
para o backend via HTTP POST, como alternativa ao fluxo principal via MQTT + IoT Hub.

Quando usar este endpoint:
  - Frontend (usuário logado no sistema) — envia leitura manual de testes;
  - Dispositivo IoT / ESP32 sem suporte MQTT — envia via HTTP com X-Api-Key.

Quando NÃO é necessário usar este endpoint:
  - Quando o ESP32 envia dados via MQTT ao IoT Hub (o consumidor IoT Hub
    lida com o armazenamento automaticamente sem passar por este endpoint).

Fluxo de autenticação (aceita dois métodos):
  1. Bearer JWT  — token do usuário logado no frontend (via Authorization header)
  2. X-Api-Key   — chave estática configurada em TELEMETRIA_API_KEY (para dispositivos)

Os 4 campos aceitos:
  temperatura / temperature    — temperatura do ar em °C
  umidade / humidity           — umidade relativa do ar em %
  umidade_solo / soil_moisture — umidade do substrato em %
  luminosidade / luminosity    — luminosidade em lux

Aceita nomes em português (padrão) e inglês (compatibilidade com dispositivos legados).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.core.dependencies import bearer_scheme, get_db
from app.models.estufa import Estufa

router = APIRouter(prefix="/api/estufas", tags=["Telemetria"])


class TelemetriaPayload(BaseModel):
    """Campos aceitos no corpo da requisição — nomes em português e inglês são equivalentes."""
    # nomes em português (padrão do sistema)
    temperatura: Optional[float] = None
    umidade: Optional[float] = None
    umidade_solo: Optional[float] = None
    luminosidade: Optional[float] = None
    # nomes em inglês (compatibilidade com dispositivos que usam firmware em inglês)
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    soil_moisture: Optional[float] = None
    luminosity: Optional[float] = None


def _first(*vals):
    """Retorna o primeiro valor não-None da lista — usado para resolver PT vs EN."""
    for v in vals:
        if v is not None:
            return v
    return None


@router.post("/{estufa_id}/telemetria", status_code=status.HTTP_204_NO_CONTENT)
async def receber_telemetria(
    estufa_id: str,
    payload: TelemetriaPayload,
    x_api_key: Optional[str] = Header(default=None, alias="X-Api-Key"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """
    Recebe uma leitura dos sensores e armazena no InfluxDB.

    Retorna HTTP 204 (sem conteúdo) em caso de sucesso — isso é intencional,
    pois o dispositivo não precisa de resposta detalhada, apenas confirmação.

    Erros possíveis:
      401 — nenhuma autenticação válida fornecida
      404 — estufa não encontrada
      422 — nenhum campo de sensor foi informado
      503 — InfluxDB indisponível no momento
    """

    # ── Verificação de autenticação ───────────────────────────────────────────
    autenticado = False

    # método 1: API Key para dispositivos IoT (comparação direta com a chave configurada)
    if x_api_key and settings.telemetria_api_key and x_api_key == settings.telemetria_api_key:
        autenticado = True

    # método 2: JWT do usuário logado no frontend
    if not autenticado and credentials and credentials.scheme.lower() == "bearer":
        try:
            from app.services.token_service import verify_access_token
            jwt_payload = verify_access_token(credentials.credentials)
            if jwt_payload.get("sub"):
                autenticado = True
        except Exception:
            pass

    if not autenticado:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticação necessária: forneça Bearer token (usuário) ou X-Api-Key (dispositivo).",
        )

    # ── Verifica se a estufa existe ───────────────────────────────────────────
    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    if not estufa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Estufa não encontrada.")

    # ── Resolve os campos (português tem prioridade sobre inglês) ─────────────
    temperatura  = _first(payload.temperatura,  payload.temperature)
    umidade      = _first(payload.umidade,      payload.humidity)
    umidade_solo = _first(payload.umidade_solo, payload.soil_moisture)
    luminosidade = _first(payload.luminosidade, payload.luminosity)

    # rejeita se nenhum sensor foi informado
    if all(v is None for v in [temperatura, umidade, umidade_solo, luminosidade]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Pelo menos um campo de sensor deve ser informado.",
        )

    # ── Grava no InfluxDB ─────────────────────────────────────────────────────
    from app.db.influx.influx import influx_db
    try:
        await influx_db.write_telemetry(
            estufa_id=estufa_id,
            temperatura=temperatura,
            umidade=umidade,
            umidade_solo=umidade_solo,
            luminosidade=luminosidade,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"InfluxDB indisponível: {exc}",
        )
