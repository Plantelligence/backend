"""Modelo SQLAlchemy para tokens JWT (refresh, revogacao, reset de senha)."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, String, Index

from app.db.postgres.Base import Base


class Token(Base):
    __tablename__ = "tokens"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    token_hash = Column(String, nullable=True, index=True)
    jti = Column(String, nullable=True, index=True)
    token_type = Column(String, nullable=False)  # refresh | access_revocation | password_reset
    expires_at = Column(String, nullable=False)
    revoked = Column(Boolean, nullable=False, default=False)
    revoked_at = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_tokens_hash_type", "token_hash", "token_type"),
        Index("ix_tokens_jti_type", "jti", "token_type"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "userId": self.user_id,
            "tokenHash": self.token_hash,
            "jti": self.jti,
            "type": self.token_type,
            "expiresAt": self.expires_at,
            "revoked": bool(self.revoked),
            "revokedAt": self.revoked_at,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
