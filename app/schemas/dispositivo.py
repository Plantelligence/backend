"""
Schemas Pydantic para validação dos dados de dispositivos IoT.

Schemas definem o "contrato" entre o frontend e o backend:
  - CriarDispositivo: o que o frontend deve enviar para cadastrar um dispositivo;
  - AtualizarDispositivo: o que pode ser alterado depois do cadastro;
  - DispositivoResposta: o que o backend retorna ao frontend em cada operação.

Nota técnica: este arquivo usa a sintaxe `str | None = None` em vez de
`Optional[str]` com `from __future__ import annotations` para garantir
compatibilidade correta com o Pydantic v2 na resolução de tipos opcionais.
"""

from pydantic import BaseModel, ConfigDict


class CriarDispositivo(BaseModel):
    """
    Dados necessários para registrar um novo dispositivo.
    O identificador é opcional — se não informado, um ID único é gerado automaticamente.
    """
    nome: str           # nome amigável para exibição no dashboard (ex.: "Sensor Temperatura A")
    tipo: str           # categoria do dispositivo (ex.: "sensor-temperatura", "atuador-irrigacao")
    identificador: str | None = None  # serial ou nome do hardware (gerado automaticamente se omitido)


class AtualizarDispositivo(BaseModel):
    """
    Campos que podem ser alterados em um dispositivo já cadastrado.
    Todos são opcionais — apenas os campos informados serão atualizados.
    """
    nome: str | None = None   # novo nome para exibição no dashboard
    ativo: bool | None = None  # True = ativo (recebendo dados), False = desativado


class DispositivoResposta(BaseModel):
    """
    Dados retornados pelo backend após criar, listar ou atualizar um dispositivo.

    Os campos de IoT Hub (iothub_*) e MQTT são retornados apenas quando o dispositivo
    está registrado no Azure IoT Hub:
      - iothub_device_id: ID único do dispositivo no IoT Hub
      - iothub_sas_token: token de autenticação MQTT (retornado APENAS na criação e renovação)
      - mqtt_server:      endereço do servidor MQTT (ex.: meuhub.azure-devices.net)
      - mqtt_port:        porta MQTT com TLS (sempre 8883 para o IoT Hub)
      - mqtt_username:    usuário no formato exigido pelo Azure IoT Hub
      - mqtt_topic_pub:   tópico onde o ESP32 publica dados dos sensores
      - mqtt_topic_sub:   tópico de onde o ESP32 recebe comandos do sistema
    """
    id: str
    nome: str
    tipo: str
    identificador: str
    ativo: bool
    estufa_id: str

    iothub_device_id: str | None = None
    iothub_sas_token: str | None = None
    mqtt_server:      str | None = None
    mqtt_port:        int | None = None
    mqtt_username:    str | None = None
    mqtt_topic_pub:   str | None = None
    mqtt_topic_sub:   str | None = None

    # from_attributes=True permite criar o schema diretamente de um objeto SQLAlchemy
    model_config = ConfigDict(from_attributes=True)
