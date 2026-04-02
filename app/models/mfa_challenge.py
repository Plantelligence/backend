"""Modelo SQLAlchemy para desafios MFA por email."""

from __future__ import annotations

from sqlalchemy import Column, Integer, JSON, String

from app.db.postgres.Base import Base


class MfaChallenge(Base):
    __tablename__ = "mfa_challenges"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    code_hash = Column(String, nullable=False)
    expires_at = Column(String, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    mfa_metadata = Column(JSON, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "userId": self.user_id,
            "codeHash": self.code_hash,
            "expiresAt": self.expires_at,
            "attempts": self.attempts,
            "metadata": self.mfa_metadata or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
