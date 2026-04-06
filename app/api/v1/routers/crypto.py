# rotas de demonstração de criptografia (RSA + AES)

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.dependencies import get_current_user
from app.crypto.communication_service import (
    get_communication_public_key,
    simulate_secure_message,
    verify_secure_message,
)

router = APIRouter(prefix="/api/crypto", tags=["crypto"])


class SimulateRequest(BaseModel):
    message: str


@router.get("/public-key")
async def public_key(_: dict = Depends(get_current_user)) -> dict:
    return {"publicKey": get_communication_public_key()}


@router.post("/simulate")
async def simulate(payload: SimulateRequest, _: dict = Depends(get_current_user)) -> dict:
    if not payload.message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mensagem e obrigatoria.")

    simulation = simulate_secure_message(payload.message)
    return {
        **simulation,
        "verification": verify_secure_message(simulation),
    }
