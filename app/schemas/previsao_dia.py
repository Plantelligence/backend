from pydantic import BaseModel, Field
from datetime import date, datetime

# Modelo de previsao diaria usada pela API.
class PrevisaoDia(BaseModel):
    data: date = Field(..., description="Data da previsao")
    temperatura_min: float = Field(..., description="Temperatura minima")
    temperatura_max: float = Field(..., description="Temperatura maxima")
    umidade_min: float = Field(..., description="Umidade minima")
    umidade_max: float = Field(..., description="Umidade maxima")
    
    # Percentual de chuva validado entre 0 e 100.
    chance_chuva: float = Field(..., ge=0, le=100, description="Chance de chuva em %")
    velocidade_vento: float = Field(..., description="Velocidade do vento em km/h")
    
    # Identificador da estufa associada.
    estufa_id: str = Field(..., description="ID da estufa")
    gerado_em: datetime = Field(..., description="Data e hora da previsao")
