# desafios MFA por e-mail: geração, validação e controle de tentativas

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.config.settings import settings
from app.core.security import hash_token
from app.db.postgres.session import get_session
from app.models.mfa_challenge import MfaChallenge
from app.services.email_service import send_mfa_code_email
from app.services.security_logger import log_security_event

MFA_TTL_SECONDS = 300
MAX_ATTEMPTS = 5


def create_mfa_challenge(user: dict, metadata: dict | None = None) -> dict:
    if not user.get("id") or not user.get("email"):
        raise ValueError("Dados do usuario invalidos para MFA.")

    with get_session() as db:
        db.query(MfaChallenge).filter(MfaChallenge.user_id == user["id"]).delete(synchronize_session=False)

    code = str(random.randint(0, 999999)).zfill(6)
    challenge_id = str(uuid4())
    expires_at = (datetime.now(UTC) + timedelta(seconds=MFA_TTL_SECONDS)).isoformat()

    with get_session() as db:
        db.add(MfaChallenge(
            id=challenge_id,
            user_id=user["id"],
            code_hash=hash_token(code),
            expires_at=expires_at,
            attempts=0,
            mfa_metadata=metadata or {},
        ))

    smtp_configured = bool(settings.smtp_user and settings.smtp_password)
    smtp_success = False

    if smtp_configured:
        try:
            send_mfa_code_email(user["email"], code, expires_at)
            smtp_success = True
        except Exception as exc:
            log_security_event("mfa_delivery_failed", user_id=user["id"], metadata={"reason": str(exc)})
            print(f"[MFA] SMTP falhou — email={user['email']} code={code}", flush=True)
    else:
        print(f"[MFA] SMTP nao configurado — email={user['email']} code={code}", flush=True)
        log_security_event("mfa_delivery_skipped", user_id=user["id"], metadata={"reason": "smtp_not_configured"})

    log_security_event("mfa_code_sent", user_id=user["id"], metadata={"delivery": "email" if smtp_success else "log"})

    response: dict = {
        "challengeId": challenge_id,
        "expiresAt": expires_at,
    }

    if not smtp_success:
        response["debugCode"] = code

    return response


def verify_mfa_challenge(challenge_id: str, code: str, ip_address: str | None = None) -> dict:
    with get_session() as db:
        challenge = db.query(MfaChallenge).filter(MfaChallenge.id == challenge_id).first()
        challenge_dict = challenge.to_dict() if challenge else None

    if not challenge_dict:
        log_security_event("mfa_challenge_missing", metadata={"challengeId": challenge_id}, ip_address=ip_address)
        raise ValueError("Desafio MFA invalido ou expirado.")

    expires = datetime.fromisoformat(challenge_dict["expiresAt"])
    if expires <= datetime.now(UTC):
        with get_session() as db:
            db.query(MfaChallenge).filter(MfaChallenge.id == challenge_id).delete(synchronize_session=False)
        log_security_event("mfa_code_expired", user_id=challenge_dict.get("userId"), metadata={"challengeId": challenge_id}, ip_address=ip_address)
        raise ValueError("Codigo MFA expirado. Gere um novo codigo.")

    attempts = int(challenge_dict.get("attempts", 0))
    if attempts >= MAX_ATTEMPTS:
        log_security_event("mfa_challenge_locked", user_id=challenge_dict.get("userId"), metadata={"challengeId": challenge_id, "attempts": attempts}, ip_address=ip_address)
        raise PermissionError("Codigo MFA bloqueado por tentativas invalidas.")

    if hash_token(code) != challenge_dict.get("codeHash"):
        updated_attempts = attempts + 1
        with get_session() as db:
            db.query(MfaChallenge).filter(MfaChallenge.id == challenge_id).update({"attempts": updated_attempts})
        log_security_event("mfa_code_invalid", user_id=challenge_dict.get("userId"), metadata={"challengeId": challenge_id, "attempts": updated_attempts}, ip_address=ip_address)
        raise PermissionError("Codigo MFA invalido.")

    with get_session() as db:
        db.query(MfaChallenge).filter(MfaChallenge.id == challenge_id).delete(synchronize_session=False)

    return {
        "userId": challenge_dict.get("userId"),
        "metadata": challenge_dict.get("metadata", {}),
        "challenge": {"id": challenge_dict.get("id"), "expiresAt": challenge_dict.get("expiresAt")},
    }
