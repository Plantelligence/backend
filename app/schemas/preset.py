from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime


class CriarPreset(BaseModel):
    nome_cultura: str = Field(..., min_length=2, description="Nome da cultura")
    tipo_cultura: str = Field(..., min_length=2, description="Tipo da cultura")
    descricao: str | None = Field(default=None, description="Descricao do preset")
    temperatura_minima: float = Field(..., description="Temperatura minima")
    temperatura_maxima: float = Field(..., description="Temperatura maxima")
    umidade_minima: float = Field(..., description="Umidade minima")
    umidade_maxima: float = Field(..., description="Umidade maxima")
    luz_minima: float = Field(..., description="Luz minima")
    luz_maxima: float = Field(..., description="Luz maxima")


class AtualizarPreset(BaseModel):
    nome_cultura: str | None = Field(default=None, description="Nome da cultura")
    tipo_cultura: str | None = Field(default=None, description="Tipo da cultura")
    descricao: str | None = Field(default=None, description="Descricao do preset")
    temperatura_minima: float | None = Field(default=None, description="Temperatura minima")
    temperatura_maxima: float | None = Field(default=None, description="Temperatura maxima")
    umidade_minima: float | None = Field(default=None, description="Umidade minima")
    umidade_maxima: float | None = Field(default=None, description="Umidade maxima")
    luz_minima: float | None = Field(default=None, description="Luz minima")
    luz_maxima: float | None = Field(default=None, description="Luz maxima")


class PresetResposta(BaseModel):
    id: str = Field(..., description="ID do preset")
    nome_cultura: str = Field(..., description="Nome da cultura")
    tipo_cultura: str = Field(..., description="Tipo da cultura")
    descricao: str | None = Field(default=None, description="Descricao do preset")
    temperatura_minima: float = Field(..., description="Temperatura minima")
    temperatura_maxima: float = Field(..., description="Temperatura maxima")
    umidade_minima: float = Field(..., description="Umidade minima")
    umidade_maxima: float = Field(..., description="Umidade maxima")
    luz_minima: float = Field(..., description="Luz minima")
    luz_maxima: float = Field(..., description="Luz maxima")
    created_at: datetime = Field(..., description="Data e hora da criacao")
    updated_at: datetime = Field(..., description="Data e hora da atualizacao")

    model_config = ConfigDict(from_attributes=True)