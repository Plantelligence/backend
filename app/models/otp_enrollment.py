"""Modelo SQLAlchemy para setup de autenticador TOTP."""

from __future__ import annotations

from sqlalchemy import Column, Integer, String

from app.db.postgres.Base import Base


class OtpEnrollment(Base):
    __tablename__ = "otp_enrollments"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    encrypted_secret = Column(String, nullable=False)
    issuer = Column(String, nullable=True)
    account_name = Column(String, nullable=True)
    expires_at = Column(String, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "userId": self.user_id,
            "encryptedSecret": self.encrypted_secret,
            "issuer": self.issuer,
            "accountName": self.account_name,
            "expiresAt": self.expires_at,
            "attempts": self.attempts,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
