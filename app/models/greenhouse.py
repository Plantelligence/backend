"""Modelo SQLAlchemy para estufas."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, JSON, String
from sqlalchemy.orm import relationship

from app.db.postgres.Base import Base


class Greenhouse(Base):
    __tablename__ = "greenhouses"

    id = Column(String, primary_key=True)
    owner_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    flower_profile_id = Column(String, nullable=True)
    watchers = Column(JSON, nullable=False, default=list)
    alerts_enabled = Column(Boolean, nullable=False, default=True)
    last_alert_at = Column(String, nullable=True)
    # Sensores, atuadores e parametros gerais ficam em JSON para evitar
    # criar tabelas separadas por enquanto. Cada lista de sensores/atuadores
    # e um array de objetos {id, name, type, active, ...}.
    sensors = Column(JSON, nullable=True)
    actuators = Column(JSON, nullable=True)
    parameters = Column(JSON, nullable=True)

    owner = relationship("User", back_populates="greenhouses")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ownerId": self.owner_id,
            "userId": self.owner_id,
            "name": self.name,
            "flowerProfileId": self.flower_profile_id,
            "watchers": self.watchers or [],
            "alertsEnabled": bool(self.alerts_enabled),
            "lastAlertAt": self.last_alert_at,
            "sensors": self.sensors or [],
            "actuators": self.actuators or [],
            "parameters": self.parameters or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
