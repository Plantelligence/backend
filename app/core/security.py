# JWT, hash de senha e utilitários de token

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import bcrypt
import jwt

from app.config.settings import settings

JWT_ISSUER = "plantelligence-backend"


def now_utc() -> datetime:
    return datetime.now(UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _prehash_password(plain_password: str) -> str:
    # bcrypt trunca em 72 bytes; pre-hash em SHA-256 evita truncamento silencioso
    return hashlib.sha256(plain_password.encode("utf-8")).hexdigest()


def hash_password(plain_password: str) -> str:
    secret = _prehash_password(plain_password).encode("utf-8")
    return bcrypt.hashpw(secret, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Tenta o fluxo atual (sha256 + bcrypt) e cai no legado (bcrypt direto) se falhar."""
    stored = (password_hash or "").encode("utf-8")

    try:
        if bcrypt.checkpw(_prehash_password(plain_password).encode("utf-8"), stored):
            return True
    except Exception:
        pass

    # fallback para contas criadas antes do pre-hash
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), stored)
    except Exception:
        return False


def calculate_password_expiry_iso() -> str:
    return (now_utc() + timedelta(days=settings.password_expiry_days)).isoformat()


def is_password_expired(password_expires_at: str | None) -> bool:
    if not password_expires_at:
        return False
    return datetime.fromisoformat(password_expires_at) <= now_utc()


def _build_access_payload(user: dict[str, Any], jti: str) -> dict[str, Any]:
    return {
        "sub": user["id"],
        "email": user["email"],
        "role": user.get("role", "User"),
        "consent": bool(user.get("consentGiven")),
        "requiresPasswordReset": is_password_expired(user.get("passwordExpiresAt")),
        "jti": jti,
        "iss": JWT_ISSUER,
        "exp": now_utc() + timedelta(seconds=settings.access_token_ttl_seconds),
    }


def create_access_token(user: dict[str, Any]) -> dict[str, Any]:
    jti = str(uuid4())
    payload = _build_access_payload(user, jti)
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return {
        "token": token,
        "jti": jti,
        "expiresAt": payload["exp"].isoformat(),
    }


def create_refresh_token(user_id: str) -> dict[str, Any]:
    jti = str(uuid4())
    exp = now_utc() + timedelta(seconds=settings.refresh_token_ttl_seconds)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": jti,
        "iss": JWT_ISSUER,
        "exp": exp,
    }
    token = jwt.encode(payload, settings.jwt_refresh_secret, algorithm="HS256")
    return {
        "token": token,
        "jti": jti,
        "expiresAt": exp.isoformat(),
    }


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer=JWT_ISSUER)


def decode_refresh_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_refresh_secret, algorithms=["HS256"], issuer=JWT_ISSUER)
