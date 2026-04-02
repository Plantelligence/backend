"""Modelo SQLAlchemy para trilha de auditoria de seguranca."""

from __future__ import annotations

from sqlalchemy import Column, JSON, String

from app.db.postgres.Base import Base


class SecurityLog(Base):
    __tablename__ = "security_logs"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=True, index=True)
    action = Column(String, nullable=False, index=True)
    log_metadata = Column(JSON, nullable=True)
    ip_address = Column(String, nullable=True)
    hash = Column(String, nullable=False)
    prev_hash = Column(String, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "userId": self.user_id,
            "action": self.action,
            "metadata": self.log_metadata or {},
            "ipAddress": self.ip_address,
            "hash": self.hash,
            "prevHash": self.prev_hash,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
