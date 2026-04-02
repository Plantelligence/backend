"""Autenticacao de usuarios, gerenciamento de sessao e fluxo de MFA."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.config.settings import settings
from app.core.security import (
    calculate_password_expiry_iso,
    hash_password,
    hash_token,
    is_password_expired,
    verify_password,
)
from app.db.postgres.session import get_session
from app.models.login_session import LoginSession
from app.models.otp_enrollment import OtpEnrollment
from app.models.registration_challenge import RegistrationChallenge
from app.models.token import Token
from app.models.user import User
from app.services.email_service import send_mfa_code_email
from app.services.mfa_service import create_mfa_challenge, verify_mfa_challenge
from app.services.security_logger import log_security_event
from app.services.token_service import (
    issue_session_tokens,
    revoke_access_token_by_jti,
    revoke_refresh_token,
    verify_refresh_token,
)
from app.services.totp_service import (
    create_totp_setup,
    recreate_totp_setup,
    verify_totp_code_with_encrypted_secret,
)

REGISTRATION_TTL_SECONDS = 600
OTP_ENROLLMENT_TTL_SECONDS = 600
LOGIN_SESSION_TTL_SECONDS = 600

_PASSWORD_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^a-zA-Z0-9]).{8,}$"
)


def _validate_password(password: str) -> None:
    """Verifica se a senha atende a politica minima: 8 caracteres, letra maiuscula, minuscula, numero e especial."""
    if not _PASSWORD_PATTERN.match(password):
        raise ValueError(
            "A senha deve ter no minimo 8 caracteres, incluindo "
            "letra maiuscula, letra minuscula, numero e caractere especial."
        )
REGISTRATION_MAX_ATTEMPTS = 5
REGISTRATION_OTP_MAX_ATTEMPTS = 5
OTP_ENROLLMENT_MAX_ATTEMPTS = 5
ENFORCED_MFA_METHODS = ["email", "otp"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _is_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return True
    return datetime.fromisoformat(expires_at) <= datetime.now(UTC)


def map_user_document(user: User | None) -> dict | None:
    if not user:
        return None
    return user.to_dict()


def _sanitize_mfa(mfa: dict | None) -> dict | None:
    """Filtra os dados de MFA antes de enviar ao cliente, removendo o segredo TOTP cifrado."""
    if not mfa:
        return mfa
    result: dict = {}
    if "email" in mfa:
        result["email"] = {"configuredAt": (mfa["email"] or {}).get("configuredAt")}
    if "otp" in mfa:
        otp = mfa["otp"] or {}
        result["otp"] = {
            "configuredAt": otp.get("configuredAt"),
            "issuer": otp.get("issuer"),
            "accountName": otp.get("accountName"),
        }
    if "enforcedMethods" in mfa:
        result["enforcedMethods"] = mfa["enforcedMethods"]
    return result


def sanitize_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "role": user.get("role", "User"),
        "fullName": user.get("fullName"),
        "phone": user.get("phone"),
        "consentGiven": bool(user.get("consentGiven")),
        "consentTimestamp": user.get("consentTimestamp"),
        "createdAt": user.get("createdAt"),
        "updatedAt": user.get("updatedAt"),
        "lastLoginAt": user.get("lastLoginAt"),
        "passwordExpiresAt": user.get("passwordExpiresAt"),
        "deletionRequested": bool(user.get("deletionRequested")),
        "mfaEnabled": bool(user.get("mfaEnabled")),
        "mfaConfiguredAt": user.get("mfaConfiguredAt"),
        "mfa": _sanitize_mfa(user.get("mfa")),
    }


def get_user_by_id(user_id: str) -> dict | None:
    with get_session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        return map_user_document(user)


def find_user_by_email(email: str) -> dict | None:
    with get_session() as db:
        user = db.query(User).filter(User.email == email).first()
        return map_user_document(user)


def _get_login_session(session_id: str) -> dict | None:
    with get_session() as db:
        session = db.query(LoginSession).filter(LoginSession.id == session_id).first()
        return session.to_dict() if session else None


def _assert_active_login_session(session: dict | None) -> None:
    if not session or _is_expired(session.get("expiresAt")):
        raise PermissionError("Sessao de autenticacao MFA invalida ou expirada.")


def _create_login_session(user_id: str, password_expired: bool) -> dict:
    session_id = str(uuid4())
    expires_at = (datetime.now(UTC) + timedelta(seconds=LOGIN_SESSION_TTL_SECONDS)).isoformat()

    with get_session() as db:
        db.add(LoginSession(
            id=session_id,
            user_id=user_id,
            password_expired=password_expired,
            expires_at=expires_at,
        ))

    return {"sessionId": session_id, "expiresAt": expires_at}


def _update_login_session(session_id: str, updates: dict[str, Any]) -> None:
    with get_session() as db:
        session = db.query(LoginSession).filter(LoginSession.id == session_id).first()
        if not session:
            return
        if "emailChallenge" in updates:
            session.email_challenge = updates["emailChallenge"]
        if "otpEnrollment" in updates:
            session.otp_enrollment = updates["otpEnrollment"]
        if "passwordExpired" in updates:
            session.password_expired = bool(updates["passwordExpired"])


def _clear_login_session(session_id: str) -> None:
    with get_session() as db:
        db.query(LoginSession).filter(LoginSession.id == session_id).delete(synchronize_session=False)


def _create_otp_enrollment_for_user(user: dict) -> dict:
    with get_session() as db:
        db.query(OtpEnrollment).filter(OtpEnrollment.user_id == user["id"]).delete(synchronize_session=False)

    enrollment_id = str(uuid4())
    setup = create_totp_setup(user["email"], settings.mfa_issuer)
    expires_at = (datetime.now(UTC) + timedelta(seconds=OTP_ENROLLMENT_TTL_SECONDS)).isoformat()

    with get_session() as db:
        db.add(OtpEnrollment(
            id=enrollment_id,
            user_id=user["id"],
            encrypted_secret=setup["encryptedSecret"],
            issuer=setup["issuer"],
            account_name=setup["accountName"],
            expires_at=expires_at,
            attempts=0,
        ))

    return {
        "enrollmentId": enrollment_id,
        "secret": setup["secret"],
        "uri": setup["uri"],
        "issuer": setup["issuer"],
        "accountName": setup["accountName"],
        "expiresAt": expires_at,
    }


def register_user(payload: dict) -> dict:
    normalized_email = _normalize_email(payload["email"])
    _validate_password(payload["password"])
    if find_user_by_email(normalized_email):
        raise ValueError("E-mail ja cadastrado.")

    city = (payload.get("city") or "").strip()
    state = (payload.get("state") or "").strip()
    if not city:
        raise ValueError("Cidade e obrigatoria.")
    if not state:
        raise ValueError("Estado e obrigatorio.")

    with get_session() as db:
        db.query(RegistrationChallenge).filter(RegistrationChallenge.email == normalized_email).delete(synchronize_session=False)

    code = str(secrets.randbelow(1_000_000)).zfill(6)
    challenge_id = str(uuid4())
    now = _now_iso()
    expires_at = (datetime.now(UTC) + timedelta(seconds=REGISTRATION_TTL_SECONDS)).isoformat()

    with get_session() as db:
        db.add(RegistrationChallenge(
            id=challenge_id,
            email=normalized_email,
            code_hash=hash_token(code),
            password_hash=hash_password(payload["password"]),
            full_name=(payload.get("fullName") or "").strip() or None,
            phone=(payload.get("phone") or "").strip() or None,
            city=city,
            state=state,
            consent_given=bool(payload.get("consent")),
            consent_timestamp=now if payload.get("consent") else None,
            attempts=0,
            otp_attempts=0,
            expires_at=expires_at,
        ))

    smtp_configured = bool(settings.smtp_user and settings.smtp_password)
    smtp_success = False

    if smtp_configured:
        try:
            send_mfa_code_email(normalized_email, code, expires_at)
            smtp_success = True
        except Exception as exc:
            log_security_event("registration_email_failed", metadata={"email": normalized_email, "reason": str(exc)})
            print(f"[REGISTER] SMTP falhou — email={normalized_email} code={code}", flush=True)
    else:
        print(f"[REGISTER] SMTP nao configurado — email={normalized_email} code={code}", flush=True)
        log_security_event("registration_email_skipped", metadata={"email": normalized_email, "reason": "smtp_not_configured"})

    log_security_event("registration_started", metadata={"email": normalized_email})

    return {
        "challengeId": challenge_id,
        "expiresAt": expires_at,
        "debugCode": code if not smtp_success else None,
    }


def confirm_registration_email(payload: dict) -> dict:
    with get_session() as db:
        challenge = db.query(RegistrationChallenge).filter(RegistrationChallenge.id == payload["challengeId"]).first()
        challenge_dict = challenge.to_dict() if challenge else None

    if not challenge_dict:
        raise FileNotFoundError("Solicitacao de cadastro invalida ou expirada.")

    if _is_expired(challenge_dict.get("expiresAt")):
        with get_session() as db:
            db.query(RegistrationChallenge).filter(RegistrationChallenge.id == payload["challengeId"]).delete(synchronize_session=False)
        raise PermissionError("Codigo de verificacao expirado. Solicite um novo cadastro.")

    attempts = int(challenge_dict.get("attempts", 0))
    if attempts >= REGISTRATION_MAX_ATTEMPTS:
        raise PermissionError("Cadastro bloqueado por tentativas invalidas. Inicie o processo novamente.")

    if hash_token(payload["code"]) != challenge_dict.get("codeHash"):
        with get_session() as db:
            db.query(RegistrationChallenge).filter(RegistrationChallenge.id == payload["challengeId"]).update({"attempts": attempts + 1})
        raise PermissionError("Codigo de verificacao invalido.")

    otp_setup = recreate_totp_setup(challenge_dict["email"], challenge_dict.get("otpSetup") or {})
    if not otp_setup:
        otp_setup = create_totp_setup(challenge_dict["email"], settings.mfa_issuer)
        with get_session() as db:
            rc = db.query(RegistrationChallenge).filter(RegistrationChallenge.id == payload["challengeId"]).first()
            if rc:
                rc.otp_setup = {
                    "encryptedSecret": otp_setup["encryptedSecret"],
                    "issuer": otp_setup["issuer"],
                    "accountName": otp_setup["accountName"],
                }

    with get_session() as db:
        rc = db.query(RegistrationChallenge).filter(RegistrationChallenge.id == payload["challengeId"]).first()
        if rc:
            rc.email_verified_at = _now_iso()
            rc.otp_attempts = 0

    return {
        "nextStep": "otp",
        "otpSetupId": payload["challengeId"],
        "secret": otp_setup["secret"],
        "uri": otp_setup["uri"],
        "issuer": otp_setup["issuer"],
        "accountName": otp_setup["accountName"],
    }


def finalize_registration(payload: dict) -> dict:
    with get_session() as db:
        challenge = db.query(RegistrationChallenge).filter(RegistrationChallenge.id == payload["otpSetupId"]).first()
        challenge_dict = challenge.to_dict() if challenge else None

    if not challenge_dict:
        raise FileNotFoundError("Solicitacao de cadastro invalida ou expirada.")

    if not challenge_dict.get("emailVerifiedAt"):
        raise ValueError("Confirme o e-mail antes de validar o aplicativo autenticador.")

    otp_setup = challenge_dict.get("otpSetup") or {}
    encrypted_secret = otp_setup.get("encryptedSecret")
    if not encrypted_secret:
        raise ValueError("Configuracao OTP nao encontrada. Reinicie o cadastro.")

    attempts = int(challenge_dict.get("otpAttempts", 0))
    if attempts >= REGISTRATION_OTP_MAX_ATTEMPTS:
        raise PermissionError("Configuracao OTP bloqueada por tentativas invalidas. Reinicie o cadastro.")

    if not verify_totp_code_with_encrypted_secret(payload["otpCode"], encrypted_secret):
        with get_session() as db:
            db.query(RegistrationChallenge).filter(RegistrationChallenge.id == payload["otpSetupId"]).update({"otp_attempts": attempts + 1})
        raise PermissionError("Codigo do autenticador invalido.")

    with get_session() as db:
        total_users = db.query(User).count()

    role = "Admin" if total_users == 0 else "User"
    now = _now_iso()
    user_id = str(uuid4())

    mfa_config = {
        "enforcedMethods": ENFORCED_MFA_METHODS,
        "email": {"delivery": "email", "configuredAt": challenge_dict.get("emailVerifiedAt") or now},
        "otp": {
            "configuredAt": now,
            "secret": encrypted_secret,
            "issuer": otp_setup.get("issuer") or settings.mfa_issuer,
            "accountName": otp_setup.get("accountName") or challenge_dict["email"],
        },
    }

    with get_session() as db:
        db.add(User(
            id=user_id,
            email=challenge_dict["email"],
            role=role,
            password_hash=challenge_dict["passwordHash"],
            full_name=challenge_dict.get("fullName"),
            phone=challenge_dict.get("phone"),
            city=challenge_dict.get("city"),
            state=challenge_dict.get("state"),
            consent_given=bool(challenge_dict.get("consentGiven")),
            consent_timestamp=challenge_dict.get("consentTimestamp") if challenge_dict.get("consentGiven") else None,
            last_login_at=None,
            last_password_change=now,
            password_expires_at=calculate_password_expiry_iso(),
            deletion_requested=False,
            mfa_enabled=True,
            mfa_configured_at=now,
            mfa_config=mfa_config,
        ))
        db.query(RegistrationChallenge).filter(RegistrationChallenge.id == payload["otpSetupId"]).delete(synchronize_session=False)

    created = get_user_by_id(user_id)
    log_security_event("user_registered", user_id=user_id, metadata={"email": challenge_dict["email"], "role": role})
    return sanitize_user(created)


def login_user(payload: dict) -> dict:
    normalized_email = _normalize_email(payload["email"])
    user = find_user_by_email(normalized_email)
    if not user:
        log_security_event("login_failed", metadata={"reason": "unknown_email", "email": normalized_email}, ip_address=payload.get("ipAddress"))
        raise PermissionError("Credenciais invalidas.")

    if not verify_password(payload["password"], user["passwordHash"]):
        log_security_event("login_failed", user_id=user["id"], metadata={"reason": "invalid_password"}, ip_address=payload.get("ipAddress"))
        raise PermissionError("Credenciais invalidas.")

    password_expired = is_password_expired(user.get("passwordExpiresAt"))
    session = _create_login_session(user["id"], password_expired)

    otp_secret = ((user.get("mfa") or {}).get("otp") or {}).get("secret")
    otp_issuer = ((user.get("mfa") or {}).get("otp") or {}).get("issuer") or settings.mfa_issuer
    otp_account = ((user.get("mfa") or {}).get("otp") or {}).get("accountName") or user["email"]

    log_security_event("mfa_session_created", user_id=user["id"], metadata={"sessionId": session["sessionId"], "passwordExpired": password_expired}, ip_address=payload.get("ipAddress"))

    return {
        "mfaRequired": True,
        "sessionId": session["sessionId"],
        "expiresAt": session["expiresAt"],
        "passwordExpired": password_expired,
        "methods": {
            "email": {"delivery": "email"},
            "otp": {
                "configured": bool(otp_secret),
                "enrollmentRequired": not bool(otp_secret),
                "issuer": otp_issuer,
                "accountName": otp_account,
            },
        },
    }


def initiate_mfa_method(payload: dict) -> dict:
    session = _get_login_session(payload["sessionId"])
    _assert_active_login_session(session)

    user = get_user_by_id(session["userId"])
    if not user:
        _clear_login_session(payload["sessionId"])
        raise FileNotFoundError("Usuario associado a sessao nao encontrado.")

    method = payload["method"]
    if method == "email":
        challenge = create_mfa_challenge(user, metadata={"passwordExpired": bool(session.get("passwordExpired"))})
        _update_login_session(payload["sessionId"], {"emailChallenge": {"id": challenge["challengeId"], "expiresAt": challenge["expiresAt"]}})
        return {
            "method": "email",
            "configured": True,
            "challengeId": challenge["challengeId"],
            "expiresAt": challenge["expiresAt"],
            "accountName": user["email"],
        }

    if method == "otp":
        otp_secret = ((user.get("mfa") or {}).get("otp") or {}).get("secret")
        issuer = ((user.get("mfa") or {}).get("otp") or {}).get("issuer") or settings.mfa_issuer
        account_name = ((user.get("mfa") or {}).get("otp") or {}).get("accountName") or user["email"]

        if otp_secret:
            _update_login_session(payload["sessionId"], {"otpEnrollment": None})
            return {"method": "otp", "configured": True, "issuer": issuer, "accountName": account_name}

        enrollment = _create_otp_enrollment_for_user(user)
        _update_login_session(payload["sessionId"], {"otpEnrollment": {"id": enrollment["enrollmentId"], "expiresAt": enrollment["expiresAt"]}})
        return {
            "method": "otp",
            "configured": False,
            "enrollmentId": enrollment["enrollmentId"],
            "secret": enrollment["secret"],
            "uri": enrollment["uri"],
            "issuer": enrollment["issuer"],
            "accountName": enrollment["accountName"],
            "expiresAt": enrollment["expiresAt"],
        }

    raise ValueError("Metodo de MFA invalido.")


def complete_mfa(payload: dict) -> dict:
    session = _get_login_session(payload["sessionId"])
    _assert_active_login_session(session)

    user = get_user_by_id(session["userId"])
    if not user:
        _clear_login_session(payload["sessionId"])
        raise FileNotFoundError("Usuario associado a sessao nao encontrado.")

    password_expired = bool(session.get("passwordExpired"))
    method = payload["method"]

    if method == "email":
        challenge_id = (session.get("emailChallenge") or {}).get("id")
        if not challenge_id:
            raise ValueError("E necessario solicitar um novo codigo por e-mail.")
        challenge = verify_mfa_challenge(challenge_id, payload["code"], payload.get("ipAddress"))
        password_expired = bool(challenge.get("metadata", {}).get("passwordExpired", password_expired))

    elif method == "otp":
        otp_secret = ((user.get("mfa") or {}).get("otp") or {}).get("secret")
        enrollment_id = payload.get("otpEnrollmentId") or ((session.get("otpEnrollment") or {}).get("id"))

        if enrollment_id:
            with get_session() as db:
                enrollment = db.query(OtpEnrollment).filter(OtpEnrollment.id == enrollment_id).first()
                enrollment_dict = enrollment.to_dict() if enrollment else None

            if not enrollment_dict or enrollment_dict.get("userId") != user["id"]:
                _clear_login_session(payload["sessionId"])
                raise FileNotFoundError("Cadastro de autenticador invalido ou expirado. Faca login novamente.")
            if _is_expired(enrollment_dict.get("expiresAt")):
                with get_session() as db:
                    db.query(OtpEnrollment).filter(OtpEnrollment.id == enrollment_id).delete(synchronize_session=False)
                _clear_login_session(payload["sessionId"])
                raise PermissionError("Cadastro de autenticador expirado. Faca login novamente.")

            attempts = int(enrollment_dict.get("attempts", 0))
            if attempts >= OTP_ENROLLMENT_MAX_ATTEMPTS:
                with get_session() as db:
                    db.query(OtpEnrollment).filter(OtpEnrollment.id == enrollment_id).delete(synchronize_session=False)
                _clear_login_session(payload["sessionId"])
                raise PermissionError("Cadastro de autenticador bloqueado. Faca login novamente.")

            if not verify_totp_code_with_encrypted_secret(payload["code"], enrollment_dict["encryptedSecret"]):
                with get_session() as db:
                    db.query(OtpEnrollment).filter(OtpEnrollment.id == enrollment_id).update({"attempts": attempts + 1})
                raise PermissionError("Codigo do autenticador invalido.")

            now = _now_iso()
            mfa_config = {
                "enforcedMethods": ENFORCED_MFA_METHODS,
                "email": {"delivery": "email", "configuredAt": ((user.get("mfa") or {}).get("email") or {}).get("configuredAt") or user.get("createdAt") or now},
                "otp": {
                    "configuredAt": now,
                    "secret": enrollment_dict["encryptedSecret"],
                    "issuer": enrollment_dict.get("issuer") or settings.mfa_issuer,
                    "accountName": enrollment_dict.get("accountName") or user["email"],
                },
            }
            with get_session() as db:
                u = db.query(User).filter(User.id == user["id"]).first()
                if u:
                    u.mfa_enabled = True
                    u.mfa_configured_at = now
                    u.mfa_config = mfa_config
                db.query(OtpEnrollment).filter(OtpEnrollment.id == enrollment_id).delete(synchronize_session=False)

            user = get_user_by_id(user["id"])
            otp_secret = ((user.get("mfa") or {}).get("otp") or {}).get("secret")

        if not otp_secret:
            raise ValueError("Nenhum autenticador configurado para este usuario.")

        if not verify_totp_code_with_encrypted_secret(payload["code"], otp_secret):
            raise PermissionError("Codigo do autenticador invalido.")

    else:
        raise ValueError("Metodo de MFA invalido.")

    now = _now_iso()
    with get_session() as db:
        u = db.query(User).filter(User.id == user["id"]).first()
        if u:
            u.last_login_at = now

    tokens = issue_session_tokens(user)
    refreshed_user = get_user_by_id(user["id"])
    _clear_login_session(payload["sessionId"])

    log_security_event("mfa_verified", user_id=user["id"], metadata={"method": method}, ip_address=payload.get("ipAddress"))
    log_security_event("login_success", user_id=user["id"], metadata={"passwordExpired": password_expired}, ip_address=payload.get("ipAddress"))

    return {
        "user": sanitize_user(refreshed_user),
        "tokens": tokens,
        "passwordExpired": password_expired,
    }


def refresh_session(payload: dict) -> dict:
    token_payload = verify_refresh_token(payload["refreshToken"])
    user = get_user_by_id(token_payload["sub"])
    if not user:
        raise FileNotFoundError("Usuario nao encontrado.")

    tokens = issue_session_tokens(user)
    log_security_event("session_refreshed", user_id=user["id"])
    return {"user": sanitize_user(user), "tokens": tokens}


def revoke_session(payload: dict) -> None:
    refresh_token = payload.get("refreshToken")
    if refresh_token:
        revoke_refresh_token(refresh_token)

    access_jti = payload.get("accessJti")
    user_id = payload.get("userId")
    if access_jti and user_id:
        expires_at = (datetime.now(UTC) + timedelta(seconds=settings.access_token_ttl_seconds)).isoformat()
        revoke_access_token_by_jti(access_jti, user_id, expires_at)

    log_security_event("session_revoked", user_id=user_id, metadata={"hasRefreshToken": bool(refresh_token), "accessJti": access_jti})


def change_password(payload: dict) -> None:
    user = get_user_by_id(payload["userId"])
    if not user:
        raise FileNotFoundError("Usuario nao encontrado.")
    _validate_password(payload["newPassword"])

    verification = payload.get("verification") or {}
    otp_code = (verification.get("otpCode") or "").strip()
    challenge_id = (verification.get("challengeId") or "").strip()
    challenge_code = (verification.get("code") or "").strip()
    verification_method = None

    if otp_code:
        secret = ((user.get("mfa") or {}).get("otp") or {}).get("secret")
        if not secret:
            raise RuntimeError("Aplicativo autenticador nao configurado.")
        if not verify_totp_code_with_encrypted_secret(otp_code, secret):
            raise PermissionError("Codigo do autenticador invalido.")
        verification_method = "otp"

    if not verification_method and challenge_id and challenge_code:
        verify_mfa_challenge(challenge_id, challenge_code, payload.get("ipAddress"))
        verification_method = "email"

    if not verification_method:
        raise PermissionError("Confirme a operacao com MFA antes de alterar a senha.")

    if not verify_password(payload["currentPassword"], user["passwordHash"]):
        raise PermissionError("Senha atual incorreta.")

    now = _now_iso()
    with get_session() as db:
        u = db.query(User).filter(User.id == payload["userId"]).first()
        if u:
            u.password_hash = hash_password(payload["newPassword"])
            u.last_password_change = now
            u.password_expires_at = calculate_password_expiry_iso()

    log_security_event("password_changed", user_id=payload["userId"], metadata={"verificationMethod": verification_method})


def start_user_otp_enrollment(payload: dict) -> dict:
    user = get_user_by_id(payload["userId"])
    if not user:
        raise FileNotFoundError("Usuario nao encontrado.")

    enrollment = _create_otp_enrollment_for_user(user)
    log_security_event("mfa_totp_enrollment_started", user_id=payload["userId"], metadata={"context": "self_service", "enrollmentId": enrollment["enrollmentId"]}, ip_address=payload.get("ipAddress"))
    return enrollment


def complete_user_otp_enrollment(payload: dict) -> dict:
    user = get_user_by_id(payload["userId"])
    if not user:
        raise FileNotFoundError("Usuario nao encontrado.")

    with get_session() as db:
        enrollment = db.query(OtpEnrollment).filter(OtpEnrollment.id == payload["enrollmentId"]).first()
        enrollment_dict = enrollment.to_dict() if enrollment else None

    if not enrollment_dict or enrollment_dict.get("userId") != payload["userId"]:
        raise FileNotFoundError("Configuracao de autenticador invalida ou expirada.")

    if _is_expired(enrollment_dict.get("expiresAt")):
        with get_session() as db:
            db.query(OtpEnrollment).filter(OtpEnrollment.id == payload["enrollmentId"]).delete(synchronize_session=False)
        raise PermissionError("Configuracao de autenticador expirada. Inicie novamente.")

    attempts = int(enrollment_dict.get("attempts", 0))
    if attempts >= OTP_ENROLLMENT_MAX_ATTEMPTS:
        with get_session() as db:
            db.query(OtpEnrollment).filter(OtpEnrollment.id == payload["enrollmentId"]).delete(synchronize_session=False)
        raise PermissionError("Configuracao de autenticador bloqueada por tentativas invalidas.")

    if not verify_totp_code_with_encrypted_secret(payload["code"], enrollment_dict["encryptedSecret"]):
        with get_session() as db:
            db.query(OtpEnrollment).filter(OtpEnrollment.id == payload["enrollmentId"]).update({"attempts": attempts + 1})
        raise PermissionError("Codigo do autenticador invalido.")

    now = _now_iso()
    mfa_config = {
        "enforcedMethods": ENFORCED_MFA_METHODS,
        "email": {"delivery": "email", "configuredAt": ((user.get("mfa") or {}).get("email") or {}).get("configuredAt") or user.get("createdAt") or now},
        "otp": {
            "configuredAt": now,
            "secret": enrollment_dict["encryptedSecret"],
            "issuer": enrollment_dict.get("issuer") or settings.mfa_issuer,
            "accountName": enrollment_dict.get("accountName") or user["email"],
        },
    }

    with get_session() as db:
        u = db.query(User).filter(User.id == payload["userId"]).first()
        if u:
            u.mfa_enabled = True
            u.mfa_configured_at = now
            u.mfa_config = mfa_config
        db.query(OtpEnrollment).filter(OtpEnrollment.id == payload["enrollmentId"]).delete(synchronize_session=False)

    refreshed = get_user_by_id(payload["userId"])
    return sanitize_user(refreshed)


def request_password_reset(payload: dict) -> dict:
    normalized_email = _normalize_email(payload["email"])
    user = find_user_by_email(normalized_email)

    if not user:
        log_security_event("password_reset_requested", metadata={"email": normalized_email, "outcome": "unknown_user"})
        return {"delivered": True}

    raw_token = secrets.token_hex(48)
    token_hash = hash_token(raw_token)
    expires_at = (datetime.now(UTC) + timedelta(seconds=settings.password_reset_ttl_seconds)).isoformat()

    with get_session() as db:
        db.add(Token(
            id=str(uuid4()),
            user_id=user["id"],
            token_hash=token_hash,
            token_type="password_reset",
            expires_at=expires_at,
            revoked=False,
        ))

    log_security_event("password_reset_requested", user_id=user["id"], metadata={"expiresAt": expires_at})

    return {
        "delivered": True,
        "token": raw_token,
        "resetLink": f"https://www.plantelligence.cloud/password-reset?token={raw_token}",
    }


def reset_password(payload: dict) -> None:
    token_hash = hash_token(payload["token"])
    with get_session() as db:
        record = db.query(Token).filter(
            Token.token_hash == token_hash,
            Token.token_type == "password_reset",
        ).first()
        record_dict = record.to_dict() if record else None

    if not record_dict:
        raise ValueError("Token invalido.")
    if record_dict.get("revoked"):
        raise ValueError("Token ja utilizado.")
    if _is_expired(record_dict.get("expiresAt")):
        raise PermissionError("Token expirado.")

    user = get_user_by_id(record_dict["userId"])
    if not user:
        raise FileNotFoundError("Usuario nao encontrado.")

    now = _now_iso()
    with get_session() as db:
        u = db.query(User).filter(User.id == record_dict["userId"]).first()
        if u:
            u.password_hash = hash_password(payload["newPassword"])
            u.last_password_change = now
            u.password_expires_at = calculate_password_expiry_iso()

        t = db.query(Token).filter(Token.id == record_dict["id"]).first()
        if t:
            t.revoked = True
            t.revoked_at = now

    log_security_event("password_reset_completed", user_id=record_dict["userId"])


def get_user_profile(user_id: str) -> dict:
    user = get_user_by_id(user_id)
    if not user:
        raise FileNotFoundError("Usuario nao encontrado.")
    return sanitize_user(user)


def update_user_profile(payload: dict) -> dict:
    user = get_user_by_id(payload["userId"])
    if not user:
        raise FileNotFoundError("Usuario nao encontrado.")

    consent = bool(payload.get("consentGiven"))
    with get_session() as db:
        u = db.query(User).filter(User.id == payload["userId"]).first()
        if u:
            u.full_name = (payload.get("fullName") or "").strip() or None
            u.phone = (payload.get("phone") or "").strip() or None
            u.consent_given = consent
            if consent and not u.consent_timestamp:
                u.consent_timestamp = _now_iso()

    log_security_event("user_profile_updated", user_id=payload["userId"], metadata={"consentGiven": consent})
    return get_user_profile(payload["userId"])


def list_users() -> list[dict]:
    with get_session() as db:
        users = db.query(User).order_by(User.created_at.desc()).all()
        return [sanitize_user(u.to_dict()) for u in users]


def update_user_role(payload: dict) -> dict:
    actor = get_user_by_id(payload["actorUserId"])
    if not actor or actor.get("role") != "Admin":
        raise PermissionError("Apenas administradores podem alterar perfis de acesso.")

    target = get_user_by_id(payload["targetUserId"])
    if not target:
        raise FileNotFoundError("Usuario alvo nao encontrado.")

    normalized_role = "Admin" if payload.get("role") == "Admin" else "User"
    with get_session() as db:
        u = db.query(User).filter(User.id == payload["targetUserId"]).first()
        if u:
            u.role = normalized_role

    log_security_event("user_role_updated", user_id=payload["targetUserId"], metadata={"actorId": payload["actorUserId"], "role": normalized_role})
    return get_user_profile(payload["targetUserId"])


def request_data_deletion(payload: dict) -> None:
    with get_session() as db:
        u = db.query(User).filter(User.id == payload["userId"]).first()
        if u:
            u.deletion_requested = True

    log_security_event("data_deletion_requested", user_id=payload["userId"], metadata={"reason": payload.get("reason")})
