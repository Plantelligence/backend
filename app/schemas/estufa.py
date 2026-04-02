from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime

class CriarEstufa(BaseModel):
    nome: str = Field(..., description="Nome da estufa")
    estado: str = Field(..., description="Estado da estufa", min_length=2, max_length=2)
    cidade: str = Field(..., description="Cidade da estufa")
    preset_id: str | None = Field(default=None, description="ID do preset")

class AtualizarEstufa(BaseModel):
    nome: str = Field(description="Nome da estufa", default=None)
    estado: str = Field(description="Estado da estufa", default=None, min_length=2, max_length=2)
    cidade: str = Field(description="Cidade da estufa", default=None)
    preset_id: str | None = Field(default=None, description="ID do preset")
    
class EstufaResposta(BaseModel):
    id: str = Field(..., description="ID da estufa")
    nome: str = Field(..., description="Nome da estufa")
    estado: str = Field(..., description="Estado da estufa", min_length=2, max_length=2)
    cidade: str = Field(..., description="Cidade da estufa")
    created_at: datetime = Field(..., description="Data e hora da criacao")
    updated_at: datetime = Field(..., description="Data e hora da atualizacao")
    user_id: str = Field(..., description="ID do usuario")
    preset_id: str | None = Field(default=None, description="ID do preset")

    model_config = ConfigDict(from_attributes=True)