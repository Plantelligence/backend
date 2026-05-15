"""
Modelo de banco de dados para dispositivos IoT vinculados às estufas.

Cada dispositivo representa um hardware físico (sensor ou atuador) cadastrado
no sistema. No momento do cadastro, ele também é registrado no Azure IoT Hub,
que gera as credenciais de autenticação MQTT armazenadas aqui.

Tipos de dispositivo (campo `tipo`):
  sensor-temperatura, sensor-umidade, sensor-solo, sensor-luminosidade
  atuador-ventilacao, atuador-irrigacao, atuador-iluminacao

Ao excluir uma estufa, todos os dispositivos vinculados são removidos em cascata
(tanto do banco quanto do IoT Hub — ver dispositivos.py router).
"""

import uuid
from sqlalchemy import Column, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db.postgres.Base import Base


class Dispositivo(Base):
    __tablename__ = "dispositivos"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    nome          = Column(String, nullable=False)
    tipo          = Column(String, nullable=False)
    # identificador único do hardware — serial do ESP32 ou gerado automaticamente
    identificador = Column(String, unique=True, nullable=False)
    ativo         = Column(Boolean, default=True)

    # credenciais geradas pelo Azure IoT Hub no cadastro
    # iothub_sas_token não é persistido — regenerado sob demanda via /regenerar-token
    iothub_device_id   = Column(String, nullable=True)
    iothub_primary_key = Column(String, nullable=True)
    iothub_sas_token   = Column(String, nullable=True)

    # chave estrangeira para a estufa — remoção em cascata
    estufa_id = Column(String, ForeignKey("estufas.id", ondelete="CASCADE"), nullable=False)

    estufa    = relationship("Estufa",   back_populates="dispositivos")
    alertas   = relationship("Alertas",  back_populates="dispositivo", cascade="all, delete-orphan")
    historicos = relationship("Historico", back_populates="dispositivo", cascade="all, delete-orphan")
