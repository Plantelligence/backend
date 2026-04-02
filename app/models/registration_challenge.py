"""Modelo SQLAlchemy para desafios de registro de usuario."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Integer, JSON, String

from app.db.postgres.Base import Base


class RegistrationChallenge(Base):
    __tablename__ = "registration_challenges"

    id = Column(String, primary_key=True)
    email = Column(String, nullable=False, index=True)
    code_hash = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    consent_given = Column(Boolean, nullable=False, default=False)
    consent_timestamp = Column(String, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    otp_attempts = Column(Integer, nullable=False, default=0)
    email_verified_at = Column(String, nullable=True)
    otp_setup = Column(JSON, nullable=True)
    expires_at = Column(String, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "codeHash": self.code_hash,
            "passwordHash": self.password_hash,
            "fullName": self.full_name,
            "phone": self.phone,
            "city": self.city,
            "state": self.state,
            "consentGiven": bool(self.consent_given),
            "consentTimestamp": self.consent_timestamp,
            "attempts": self.attempts,
            "otpAttempts": self.otp_attempts,
            "emailVerifiedAt": self.email_verified_at,
            "otpSetup": self.otp_setup,
            "expiresAt": self.expires_at,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
