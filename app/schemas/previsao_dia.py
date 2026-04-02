from pydantic import BaseModel, Field
from datetime import date, datetime

# Esse e o coracao da previsao do tempo filtrada e validada pelo pydantic
# Aqui cada dia tem suas info primarias pra gnt n importar todo payload inutil da openWeatherMap
class PrevisaoDia(BaseModel):
    data: date = Field(..., description="Data da previsao")
    temperatura_min: float = Field(..., description="Temperatura minima")
    temperatura_max: float = Field(..., description="Temperatura maxima")
    umidade_min: float = Field(..., description="Umidade minima")
    umidade_max: float = Field(..., description="Umidade maxima")
    
    # Campo forcado de ge=0 (>= 0) le=100 (<=100) pra caso venha % zuada da API externa barrar erro la
    chance_chuva: float = Field(..., ge=0, le=100, description="Chance de chuva em %")
    velocidade_vento: float = Field(..., description="Velocidade do vento em km/h")
    
    # Referencia da estufa_id dona desse dia
    estufa_id: str = Field(..., description="ID da estufa")
    gerado_em: datetime = Field(..., description="Data e hora da previsao")
