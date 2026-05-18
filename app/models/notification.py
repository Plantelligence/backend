"""
Modelo de banco de dados para notificacoes in-app dos usuarios.

Cada notificacao representa um evento relevante que o usuario deve ser informado:
  - Metricas fora da faixa ideal
  - Dispositivos desconectados
  - Alertas climaticos
  - Acoes de automacao
  - Eventos de conta e organizacao

A notificacao e marcada como lida quando o usuario a visualiza ou descarta.
O campo `dismissed_at` indica quando o usuario descartou a notificacao.
"""

import uuid
from sqlalchemy import Column, String, Boolean, JSON, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.db.postgres.Base import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # destinatario
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # tipo do alerta (usado para filtro e preferencias)
    # Ex.: metric_out_of_range, sensor_offline, device_disconnected,
    #       weather_heat_wave, weather_frost, weather_storm, weather_strong_wind,
    #       weather_sudden_change, weather_recommendation, token_expiring,
    #       token_expired, automation_action, automation_failure,
    #       preset_changed, password_expiring, demo_expiring,
    #       weekly_report, invitation_expired, new_team_member
    notification_type = Column(String, nullable=False, index=True)

    # severidade: info | warning | critical
    severity = Column(String, nullable=False, default="info")

    # titulo curto para exibicao
    title = Column(String, nullable=False)

    # mensagem detalhada
    message = Column(Text, nullable=False)

    # contexto adicional (estufa_id, dispositivo_id, valores, etc.)
    metadata = Column(JSON, nullable=True)

    # estufa relacionada (se aplicavel)
    greenhouse_id = Column(String, ForeignKey("estufas.id", ondelete="SET NULL"), nullable=True)

    # estado de leitura
    read = Column(Boolean, nullable=False, default=False)
    read_at = Column(String, nullable=True)

    # quando o usuario descartou a notificacao
    dismissed_at = Column(String, nullable=True)

    user = relationship("User", back_populates="notifications")
    greenhouse = relationship("Estufa", back_populates="notifications")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "userId": self.user_id,
            "notificationType": self.notification_type,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "metadata": self.metadata,
            "greenhouseId": self.greenhouse_id,
            "read": self.read,
            "readAt": self.read_at,
            "dismissedAt": self.dismissed_at,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
