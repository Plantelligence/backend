from pydantic import BaseModel, Field

from .previsao_dia import PrevisaoDia
from .alertas_clima import Clima

# Modelo de resposta consolidada de clima por estufa.
class ClimaResposta(BaseModel):
    previsao: list[PrevisaoDia] = Field(..., description="Previsao do tempo")
    alertas: list[Clima] = Field(..., description="Alertas do tempo")
