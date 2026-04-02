"""Modelo SQLAlchemy para usuarios."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, String, JSON
from sqlalchemy.orm import relationship

from app.db.postgres.Base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    role = Column(String, nullable=False, default="User")
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    consent_given = Column(Boolean, nullable=False, default=False)
    consent_timestamp = Column(String, nullable=True)
    last_login_at = Column(String, nullable=True)
    last_password_change = Column(String, nullable=True)
    password_expires_at = Column(String, nullable=True)
    deletion_requested = Column(Boolean, nullable=False, default=False)
    mfa_enabled = Column(Boolean, nullable=False, default=False)
    mfa_configured_at = Column(String, nullable=True)
    mfa_config = Column(JSON, nullable=True)
    # Permissoes granulares alem do papel (Admin/User).
    # Exemplo: {"canControlActuators": true, "canEditGreenhouseParameters": false}
    permissions = Column(JSON, nullable=True)

    greenhouses = relationship("Greenhouse", back_populates="owner", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "role": self.role,
            "passwordHash": self.password_hash,
            "fullName": self.full_name,
            "phone": self.phone,
            "city": self.city,
            "state": self.state,
            "consentGiven": bool(self.consent_given),
            "consentTimestamp": self.consent_timestamp,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "lastLoginAt": self.last_login_at,
            "lastPasswordChange": self.last_password_change,
            "passwordExpiresAt": self.password_expires_at,
            "deletionRequested": bool(self.deletion_requested),
            "mfaEnabled": bool(self.mfa_enabled),
            "mfaConfiguredAt": self.mfa_configured_at,
            "mfa": self.mfa_config,
            "permissions": self.permissions or {},
        }
