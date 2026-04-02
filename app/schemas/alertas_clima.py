from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime

class ClimaTipo(str, Enum):
    frente_fria = "frente_fria"
    onda_calor = "onda_calor"
    tempestade = "tempestade"
    geada = "geada"
    granizo = "granizo"
    vento_forte = "vento_forte"
    neblina = "neblina"

class Clima(BaseModel):
    tipo: ClimaTipo = Field(..., description="Tipo de evento climatico")
    descricao: str = Field(..., description="Descricao do evento climatico")
    recomendacao: str = Field(..., description="Recomendacao para o evento climatico")
    estufa_id: str = Field(..., description="ID da estufa")
    gerado_em: datetime = Field(..., description="Data e hora do evento climatico")
