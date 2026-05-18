"""
Modelo de banco de dados para histórico de comandos enviados a atuadores.

Cada registro representa uma tentativa de enviar um comando a um dispositivo
via Azure IoT Hub. O campo `status` indica o resultado da operacao:
  - pending: comando enfileirado, aguardando envio
  - sent: enviado com sucesso ao IoT Hub
  - delivered: dispositivo confirmou recebimento (via feedback queue)
  - failed: falha no envio (IoT Hub indisponivel, dispositivo nao existe, etc.)
  - expired: comando expirou antes do dispositivo se conectar

O campo `response_payload` armazena a resposta do dispositivo quando
o comando e do tipo "direct_method" (retorno sincrono).
"""

import uuid
from sqlalchemy import Column, String, Text, JSON, Float, ForeignKey
from sqlalchemy.orm import relationship
from app.db.postgres.Base import Base


class CommandHistory(Base):
    __tablename__ = "command_history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # qual dispositivo recebeu o comando
    dispositivo_id = Column(String, ForeignKey("dispositivos.id", ondelete="CASCADE"), nullable=False)

    # tipo de comando: ligar, desligar, ajustar, custom
    command_type = Column(String, nullable=False)

    # payload enviado ao dispositivo (JSON serializado como string para compatibilidade)
    payload = Column(JSON, nullable=True)

    # metodo de envio: cloud_to_device (C2D message) ou direct_method
    delivery_method = Column(String, nullable=False, default="cloud_to_device")

    # pending | sent | delivered | failed | expired
    status = Column(String, nullable=False, default="pending")

    # mensagem de erro quando status = failed
    error_message = Column(Text, nullable=True)

    # resposta retornada pelo dispositivo (apenas direct_method)
    response_payload = Column(JSON, nullable=True)

    # quem enviou o comando (usuario ou "automation" para comandos automaticos)
    sent_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # motivo/contexto do comando (ex.: "Temperatura acima de 28°C")
    reason = Column(Text, nullable=True)

    dispositivo = relationship("Dispositivo", back_populates="command_history")
    sent_by_user = relationship("User", back_populates="sent_commands")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dispositivoId": self.dispositivo_id,
            "commandType": self.command_type,
            "payload": self.payload,
            "deliveryMethod": self.delivery_method,
            "status": self.status,
            "errorMessage": self.error_message,
            "responsePayload": self.response_payload,
            "sentByUserId": self.sent_by_user_id,
            "reason": self.reason,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
