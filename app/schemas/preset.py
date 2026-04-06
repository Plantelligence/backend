from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime

class Faixas(BaseModel):
    min: float = Field(..., description="Minimo aceitavel para a faixa")
    max: float = Field(..., description="Maximo aceitavel para a faixa")

class FaixasMetricas(BaseModel):
    critico_baixo: Faixas
    alerta_baixo: Faixas
    ideal: Faixas
    alerta_alto: Faixas
    critico_alto: Faixas

class CriarPreset(BaseModel):
    sistema: bool = Field(..., description="verifica se e um preset do sistema")
    user_id: str | None = Field(default=None, description="ID do usuario caso seja um preset do usuario")

    nome_cultura: str = Field(..., min_length=2, description="Nome da cultura")
    tipo_cultura: str = Field(..., min_length=2, description="Tipo da cultura")
    descricao: str | None = Field(default=None, description="Descricao do preset")

    temperatura: FaixasMetricas = Field(..., description="Faixas de temperatura")
    umidade: FaixasMetricas = Field(..., description="Faixas de umidade")
    luminosidade: FaixasMetricas = Field(..., description="Faixas de luminosidade")


class AtualizarPreset(BaseModel):
    sistema: bool | None = Field(default=None, description="verifica se e um preset do sistema")
    user_id: str | None = Field(default=None, description="ID do usuario")
    nome_cultura: str | None = Field(default=None, description="Nome da cultura")
    tipo_cultura: str | None = Field(default=None, description="Tipo da cultura")
    descricao: str | None = Field(default=None, description="Descricao do preset")
    temperatura: FaixasMetricas | None = Field(default=None, description="Faixas de temperatura")
    umidade: FaixasMetricas | None = Field(default=None, description="Faixas de umidade")
    luminosidade: FaixasMetricas | None = Field(default=None, description="Faixas de luminosidade")


class CriarPresetUsuario(BaseModel):
    """Payload para criacao de presets personalizados do usuario autenticado."""

    nome_cultura: str = Field(..., min_length=2, max_length=80, description="Nome da cultura")
    tipo_cultura: str = Field(default="Cogumelos", min_length=2, max_length=40, description="Tipo da cultura")
    descricao: str | None = Field(default=None, max_length=400, description="Descricao do preset")
    temperatura: FaixasMetricas = Field(..., description="Faixas de temperatura")
    umidade: FaixasMetricas = Field(..., description="Faixas de umidade")
    luminosidade: FaixasMetricas = Field(..., description="Faixas de luminosidade")


class AtualizarPresetUsuario(BaseModel):
    """Campos permitidos para editar presets personalizados do usuario."""

    nome_cultura: str | None = Field(default=None, min_length=2, max_length=80, description="Nome da cultura")
    tipo_cultura: str | None = Field(default=None, min_length=2, max_length=40, description="Tipo da cultura")
    descricao: str | None = Field(default=None, max_length=400, description="Descricao do preset")
    temperatura: FaixasMetricas | None = Field(default=None, description="Faixas de temperatura")
    umidade: FaixasMetricas | None = Field(default=None, description="Faixas de umidade")
    luminosidade: FaixasMetricas | None = Field(default=None, description="Faixas de luminosidade")


class PresetResposta(BaseModel):
    id: str = Field(..., description="ID do preset")
    sistema: bool = Field(..., description="verifica se e um preset do sistema")
    user_id: str | None = Field(default=None, description="ID do usuario caso seja um preset do usuario")
    nome_cultura: str = Field(..., description="Nome da cultura")
    tipo_cultura: str = Field(..., description="Tipo da cultura")
    descricao: str | None = Field(default=None, description="Descricao do preset")
    temperatura: FaixasMetricas = Field(..., description="Faixas de temperatura")
    umidade: FaixasMetricas = Field(..., description="Faixas de umidade")
    luminosidade: FaixasMetricas = Field(..., description="Faixas de luminosidade")
    created_at: datetime = Field(..., description="Data e hora da criacao")
    updated_at: datetime = Field(..., description="Data e hora da atualizacao")

    model_config = ConfigDict(from_attributes=True)
