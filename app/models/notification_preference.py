"""
Modelo de banco de dados para preferencias de notificacao por usuario.

Cada usuario pode configurar:
  - Quais canais de notificacao deseja receber (email, in-app)
  - Quais tipos de notificacao quer ou nao quer
  - Horario de silencio (quiet hours) — notificacoes nao criticas sao silenciadas
"""

import uuid
from sqlalchemy import Column, String, Boolean, JSON
from sqlalchemy.orm import relationship
from app.db.postgres.Base import Base


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    user_id = Column(String, nullable=False, unique=True, index=True)

    # canais habilitados
    channel_email = Column(Boolean, nullable=False, default=True)
    channel_inapp = Column(Boolean, nullable=False, default=True)

    # tipos de notificacao bloqueados pelo usuario (lista de strings)
    # Ex.: ["weekly_report", "preset_changed"]
    blocked_types = Column(JSON, nullable=False, default=list)

    # horario de silencio — notificacoes nao criticas sao silenciadas
    quiet_hours_start = Column(String, nullable=True)  # Ex.: "22:00"
    quiet_hours_end = Column(String, nullable=True)    # Ex.: "07:00"

    # se quiet hours se aplicam a alertas de severidade warning
    quiet_hours_include_warning = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="notification_preferences")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "userId": self.user_id,
            "channelEmail": self.channel_email,
            "channelInapp": self.channel_inapp,
            "blockedTypes": self.blocked_types or [],
            "quietHoursStart": self.quiet_hours_start,
            "quietHoursEnd": self.quiet_hours_end,
            "quietHoursIncludeWarning": self.quiet_hours_include_warning,
        }
