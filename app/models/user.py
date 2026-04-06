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
    blocked = Column(Boolean, nullable=False, default=False)
    blocked_at = Column(String, nullable=True)
    blocked_reason = Column(String, nullable=True)
    organization_name = Column(String, nullable=True)
    organization_key = Column(String, nullable=True, index=True)
    organization_owner_id = Column(String, nullable=True, index=True)
    created_by_user_id = Column(String, nullable=True, index=True)
    invitation_sent_at = Column(String, nullable=True)
    invitation_accepted_at = Column(String, nullable=True)
    is_demo_account = Column(Boolean, nullable=False, default=False)
    demo_expires_at = Column(String, nullable=True)
    deletion_requested = Column(Boolean, nullable=False, default=False)
    mfa_enabled = Column(Boolean, nullable=False, default=False)
    mfa_configured_at = Column(String, nullable=True)
    mfa_config = Column(JSON, nullable=True)
    # Permissoes granulares alem do papel (Admin/User).
    # Exemplo: {"canControlActuators": true, "canEditGreenhouseParameters": false}
    permissions = Column(JSON, nullable=True)

    # Compatibilidade com o modelo legado (tabelas em portugues).
    estufas = relationship("Estufa", back_populates="user", cascade="all, delete-orphan")
    historicos = relationship("Historico", back_populates="user", cascade="all, delete-orphan")
    alertas = relationship("Alertas", back_populates="user", cascade="all, delete-orphan")
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
            "blocked": bool(self.blocked),
            "blockedAt": self.blocked_at,
            "blockedReason": self.blocked_reason,
            "organizationName": self.organization_name,
            "organizationKey": self.organization_key,
            "organizationOwnerId": self.organization_owner_id,
            "createdByUserId": self.created_by_user_id,
            "invitationSentAt": self.invitation_sent_at,
            "invitationAcceptedAt": self.invitation_accepted_at,
            "isDemoAccount": bool(self.is_demo_account),
            "demoExpiresAt": self.demo_expires_at,
            "deletionRequested": bool(self.deletion_requested),
            "mfaEnabled": bool(self.mfa_enabled),
            "mfaConfiguredAt": self.mfa_configured_at,
            "mfa": self.mfa_config,
            "permissions": self.permissions or {},
        }
