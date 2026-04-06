# rotas públicas do site institucional (sem autenticação)

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from app.services.email_service import send_contact_request_email, send_contact_confirmation_email

router = APIRouter(prefix="/api/site", tags=["site"])


class ContactRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    company: str | None = Field(default=None, max_length=160)
    subject: str = Field(min_length=3, max_length=180)
    message: str = Field(min_length=10, max_length=4000)

    @field_validator('company', mode='before')
    @classmethod
    def empty_company_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


@router.post("/contact", status_code=status.HTTP_202_ACCEPTED)
async def contact(payload: ContactRequest, request: Request) -> dict[str, str]:
    try:
        email = payload.email.strip().lower()
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
            raise ValueError("E-mail invalido.")

        send_contact_request_email(
            name=payload.name.strip(),
            email=email,
            company=(payload.company or "").strip() or None,
            subject=payload.subject.strip(),
            message=payload.message.strip(),
        )
        send_contact_confirmation_email(
            name=payload.name.strip(),
            email=email,
            subject=payload.subject.strip(),
        )
        return {"message": "Mensagem recebida com sucesso. Retornaremos em breve."}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
