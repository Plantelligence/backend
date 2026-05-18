"""
Schemas Pydantic para comandos enviados a dispositivos/atuadores.

Tipos de comando suportados:
  - ligar: ativa o atuador (ex.: ligar ventilacao, ligar irrigacao)
  - desligar: desativa o atuador
  - ajustar: define um valor especifico (ex.: intensidade luminosa = 70%)
  - custom: comando arbitrario definido pelo usuario

Metodo de entrega:
  - cloud_to_device: mensagem enfileirada no IoT Hub (assincrono, sem resposta)
  - direct_method: chamada sincrona com resposta do dispositivo (timeout configuravel)
"""

from pydantic import BaseModel, ConfigDict, Field


class ComandoLigar(BaseModel):
    """Liga um atuador."""
    command: str = Field(default="ligar", pattern="^ligar$")


class ComandoDesligar(BaseModel):
    """Desliga um atuador."""
    command: str = Field(default="desligar", pattern="^desligar$")


class ComandoAjustar(BaseModel):
    """Ajusta um parametro do atuador para um valor especifico."""
    command: str = Field(default="ajustar", pattern="^ajustar$")
    parameter: str = Field(..., min_length=1, max_length=60, description="Nome do parametro (ex.: intensidade, duracao, vazao)")
    value: float = Field(..., description="Valor desejado (ex.: 70.0 para 70%)")
    unit: str | None = Field(default=None, max_length=20, description="Unidade de medida (ex.: %, segundos, L/min)")


class ComandoCustom(BaseModel):
    """Envia um comando arbitrario ao dispositivo."""
    command: str = Field(..., min_length=1, max_length=60, description="Nome do comando (ex.: reiniciar, calibrar, status)")
    payload: dict | None = Field(default=None, description="Payload arbitrario enviado ao dispositivo")


class EnviarComandoRequest(BaseModel):
    """
    Payload unificado para envio de comandos.
    O campo `command_type` define qual acao executar.
    O campo `payload` e opcional e depende do tipo de comando.
    """
    command_type: str = Field(..., min_length=1, max_length=60, description="ligar | desligar | ajustar | custom")
    payload: dict | None = Field(default=None, description="Dados do comando (obrigatorio para ajustar e custom)")
    delivery_method: str = Field(default="cloud_to_device", description="cloud_to_device | direct_method")
    timeout_seconds: int = Field(default=30, ge=5, le=300, description="Timeout para direct_method")
    reason: str | None = Field(default=None, max_length=500, description="Motivo/contexto do comando")


class ComandoResposta(BaseModel):
    """Resposta da API apos envio de comando."""
    commandId: str
    dispositivoId: str
    commandType: str
    deliveryMethod: str
    status: str
    errorMessage: str | None = None
    responsePayload: dict | None = None
    createdAt: str | None = None

    model_config = ConfigDict(from_attributes=True)


class HistoricoComandoResposta(BaseModel):
    """Item do historico de comandos."""
    id: str
    dispositivoId: str
    commandType: str
    payload: dict | None = None
    deliveryMethod: str
    status: str
    errorMessage: str | None = None
    responsePayload: dict | None = None
    sentByUserId: str | None = None
    reason: str | None = None
    createdAt: str | None = None

    model_config = ConfigDict(from_attributes=True)
