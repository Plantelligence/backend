"""Modelo SQLAlchemy para sessoes temporarias de login+MFA."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, JSON, String

from app.db.postgres.Base import Base


class LoginSession(Base):
    __tablename__ = "login_sessions"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    password_expired = Column(Boolean, nullable=False, default=False)
    expires_at = Column(String, nullable=False)
    email_challenge = Column(JSON, nullable=True)
    otp_enrollment = Column(JSON, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "userId": self.user_id,
            "passwordExpired": bool(self.password_expired),
            "expiresAt": self.expires_at,
            "emailChallenge": self.email_challenge,
            "otpEnrollment": self.otp_enrollment,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
