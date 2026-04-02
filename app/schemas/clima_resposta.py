from pydantic import BaseModel, Field

from .previsao_dia import PrevisaoDia
from .alertas_clima import Clima

# O envelopador de envio p/ o endpoint local do Clima de Estufa. 
# Ele agrega do "Previsao_Dia" um arr de 5 dias e um arr generico pra eventuais Alertas q estouraram nos max.
class ClimaResposta(BaseModel):
    previsao: list[PrevisaoDia] = Field(..., description="Previsao do tempo")
    alertas: list[Clima] = Field(..., description="Alertas do tempo")
