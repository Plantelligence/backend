from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional
from app.schemas.preset import PresetResposta

class CriarEstufa(BaseModel):
    nome: str = Field(..., description="Nome da estufa")
    cep: str = Field(..., description="CEP da estufa (apenas digitos)", min_length=8, max_length=9)
    estado: str | None = Field(default=None, description="Estado da estufa", min_length=2, max_length=2)
    cidade: str | None = Field(default=None, description="Cidade da estufa")

    preset_id: str | None = Field(default=None, description="ID do preset")

class AtualizarEstufa(BaseModel):
    nome: str | None = Field(description="Nome da estufa", default=None)
    cep: str | None = Field(description="CEP da estufa (apenas digitos)", default=None)
    estado: str | None = Field(description="Estado da estufa", default=None, min_length=2, max_length=2)
    cidade: str | None = Field(description="Cidade da estufa", default=None)
    preset_id: str | None = Field(default=None, description="ID do preset")
    responsible_user_ids: list[str] | None = Field(default=None, description="IDs dos usuários responsáveis")
    alerts_enabled: bool | None = Field(default=None, description="Se os alertas automáticos estão ativos")
    
class EstufaResposta(BaseModel):
    id: str = Field(..., description="ID da estufa")
    nome: str = Field(..., description="Nome da estufa")
    estado: str = Field(..., description="Estado da estufa", min_length=2, max_length=2)
    cidade: str = Field(..., description="Cidade da estufa")
    cep: str | None = Field(default=None, description="CEP da estufa")
    created_at: datetime = Field(..., description="Data e hora da criacao")
    updated_at: datetime = Field(..., description="Data e hora da atualizacao")
    user_id: str = Field(..., description="ID do usuario")
    preset_id: str | None = Field(default=None, description="ID do preset")
    responsible_user_ids: list[str] = Field(default_factory=list, description="IDs dos usuários responsáveis")
    alerts_enabled: bool = Field(default=True, description="Se os alertas automáticos estão ativos")
    last_alert_at: str | None = Field(default=None, description="Data/hora ISO do último alerta enviado")
    watchers_details: list[dict] = Field(default_factory=list, description="Resumo dos responsáveis da estufa")
    
    preset: Optional[PresetResposta] = Field(default=None, description="Preset vinculado (se houver)")

    model_config = ConfigDict(from_attributes=True)


EstufaResposta.model_rebuild()
