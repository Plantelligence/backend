"""Servico de tokens JWT com persistencia em PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import jwt

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_token,
)
from app.db.postgres.session import get_session
from app.models.token import Token
from app.services.security_logger import log_security_event


def _now_iso() -> str:
    """Retorna horario atual em ISO UTC para persistencia."""
    return datetime.now(UTC).isoformat()


def issue_session_tokens(user: dict) -> dict:
    """Emite e persiste par access/refresh token."""

    access = create_access_token(user)
    refresh = create_refresh_token(user["id"])

    token_id = str(uuid4())
    with get_session() as db:
        db.add(Token(
            id=token_id,
            user_id=user["id"],
            token_hash=hash_token(refresh["token"]),
            jti=refresh["jti"],
            token_type="refresh",
            expires_at=refresh["expiresAt"],
            revoked=False,
        ))

    log_security_event("refresh_token_issued", user_id=user["id"], metadata={"jti": refresh["jti"]})
    return {"access": access, "refresh": refresh}


def verify_access_token(token: str) -> dict:
    """Valida access token e bloqueia jti revogado."""

    payload = decode_access_token(token)
    jti = payload.get("jti")
    if jti:
        with get_session() as db:
            revoked = db.query(Token).filter(
                Token.token_type == "access_revocation",
                Token.jti == jti,
            ).first()
        if revoked:
            raise jwt.InvalidTokenError("Token has been revoked")
    return payload


def verify_refresh_token(token: str) -> dict:
    """Valida refresh token e confere hash persistido."""

    payload = decode_refresh_token(token)
    with get_session() as db:
        record = db.query(Token).filter(
            Token.token_hash == hash_token(token),
            Token.token_type == "refresh",
        ).first()
        record_dict = record.to_dict() if record else None

    if not record_dict or record_dict.get("revoked"):
        raise jwt.InvalidTokenError("Refresh token invalid")
    return payload


def revoke_refresh_token(token: str) -> None:
    """Revoga refresh token pelo hash."""

    with get_session() as db:
        record = db.query(Token).filter(
            Token.token_hash == hash_token(token),
            Token.token_type == "refresh",
        ).first()
        if record:
            record.revoked = True
            record.revoked_at = _now_iso()


def revoke_access_token_by_jti(jti: str, user_id: str, expires_at: str) -> None:
    """Registra revogacao de access token por jti."""

    with get_session() as db:
        db.add(Token(
            id=str(uuid4()),
            user_id=user_id,
            jti=jti,
            token_type="access_revocation",
            expires_at=expires_at,
            revoked=True,
        ))


def cleanup_expired_tokens() -> None:
    """Limpa tokens e challenges expirados."""

    now = _now_iso()
    with get_session() as db:
        db.query(Token).filter(Token.expires_at <= now).delete(synchronize_session=False)

    from app.models.mfa_challenge import MfaChallenge
    with get_session() as db:
        db.query(MfaChallenge).filter(MfaChallenge.expires_at <= now).delete(synchronize_session=False)
