# autenticação, sessão e fluxo de MFA

from __future__ import annotations

import re
import secrets
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import or_

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
from app.models.mfa_challenge import MfaChallenge
from app.models.otp_enrollment import OtpEnrollment
from app.models.registration_challenge import RegistrationChallenge
from app.models.alertas import Alertas
from app.models.dispositivo import Dispositivo
from app.models.estufa import Estufa
from app.models.greenhouse import Greenhouse
from app.models.historico import Historico
from app.models.preset import Preset
from app.models.security_log import SecurityLog
from app.models.token import Token
from app.models.user import User
from app.services.email_service import send_mfa_code_email, send_user_invitation_email
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
    if not _PASSWORD_PATTERN.match(password):
        raise ValueError(
            "A senha deve ter no minimo 8 caracteres, incluindo "
            "letra maiuscula, letra minuscula, numero e caractere especial."
        )
REGISTRATION_MAX_ATTEMPTS = 5
REGISTRATION_OTP_MAX_ATTEMPTS = 5
OTP_ENROLLMENT_MAX_ATTEMPTS = 5
ENFORCED_MFA_METHODS = ["email", "otp"]

_ROLE_ALIASES = {
    "admin": "Admin",
    "administrador": "Admin",
    "reader": "Reader",
    "leitor": "Reader",
    "collaborator": "Collaborator",
    "colaborador": "Collaborator",
    "user": "Collaborator",
    "operador": "Collaborator",
}

DEMO_TRIAL_DAYS = 30
_LAST_DEMO_PURGE_AT: datetime | None = None
_DEMO_PURGE_INTERVAL_SECONDS = 300


def _normalize_organization_name(value: str | None) -> str:
    return (value or "").strip()


def _organization_key_from_name(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    key = key.strip("-")
    return key or f"org-{uuid4().hex[:8]}"


def _organization_scope(user: dict | None) -> tuple[str | None, str | None]:
    if not user:
        return None, None
    owner_id = (user.get("organizationOwnerId") or "").strip() or user.get("id")
    org_key = (user.get("organizationKey") or "").strip() or None
    return owner_id, org_key


def _same_organization(actor: dict | None, target: dict | None) -> bool:
    actor_owner, actor_key = _organization_scope(actor)
    target_owner, target_key = _organization_scope(target)
    if actor_owner and target_owner and actor_owner == target_owner:
        return True
    if actor_key and target_key and actor_key == target_key:
        return True
    return False


def purge_expired_demo_organizations(force: bool = False) -> int:
    # bloqueia usuários e marca para exclusão; não deleta dados ainda
    global _LAST_DEMO_PURGE_AT

    now_dt = datetime.now(UTC)
    if not force and _LAST_DEMO_PURGE_AT and (now_dt - _LAST_DEMO_PURGE_AT).total_seconds() < _DEMO_PURGE_INTERVAL_SECONDS:
        return 0
    _LAST_DEMO_PURGE_AT = now_dt

    now_iso = now_dt.isoformat()
    with get_session() as db:
        expired_owners = [
            row[0]
            for row in db.query(User.id)
            .filter(
                User.is_demo_account.is_(True),
                User.role == "Admin",
                User.id == User.organization_owner_id,
                User.demo_expires_at.isnot(None),
                User.demo_expires_at <= now_iso,
            )
            .all()
        ]

        if not expired_owners:
            return 0

        members = db.query(User).filter(
            or_(User.organization_owner_id.in_(expired_owners), User.id.in_(expired_owners))
        ).all()
        member_ids = [item.id for item in members]

        if member_ids:
            db.query(Token).filter(Token.user_id.in_(member_ids)).delete(synchronize_session=False)
            db.query(LoginSession).filter(LoginSession.user_id.in_(member_ids)).delete(synchronize_session=False)
            db.query(OtpEnrollment).filter(OtpEnrollment.user_id.in_(member_ids)).delete(synchronize_session=False)
            db.query(MfaChallenge).filter(MfaChallenge.user_id.in_(member_ids)).delete(synchronize_session=False)

            db.query(User).filter(User.id.in_(member_ids)).update(
                {
                    User.blocked: True,
                    User.blocked_reason: "Acesso de demonstracao expirado.",
                    User.blocked_at: now_iso,
                    User.deletion_requested: True,
                },
                synchronize_session=False,
            )

            log_security_event(
                "demo_organization_expired",
                metadata={"ownerIds": expired_owners, "affectedUsers": len(member_ids)},
            )

        return len(member_ids)


def _normalize_role(role: str | None) -> str:
    raw = (role or "").strip().lower()
    return _ROLE_ALIASES.get(raw, "Collaborator")


def _role_label(role: str) -> str:
    if role == "Admin":
        return "Administrador"
    if role == "Reader":
        return "Leitor"
    return "Colaborador"


def _permission_level(user: dict) -> str:
    # label de exibição no front; não interfere no RBAC
    role = _normalize_role(user.get("role"))
    if role == "Admin":
        owner_id = (user.get("organizationOwnerId") or "").strip()
        if owner_id and owner_id == user.get("id"):
            return "AdminMaster"
        return "AdminUsers"
    if role == "Reader":
        return "Reader"
    return "Collaborator"


def _normalize_encrypted_secret(value: Any) -> dict | None:
    # campo é String no schema legado; aceita dict ou JSON string
    if not value:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


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
    # remove o segredo TOTP antes de expor ao cliente
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
        "role": _normalize_role(user.get("role")),
        "permissionLevel": _permission_level(user),
        "fullName": user.get("fullName"),
        "phone": user.get("phone"),
        "consentGiven": bool(user.get("consentGiven")),
        "consentTimestamp": user.get("consentTimestamp"),
        "createdAt": user.get("createdAt"),
        "updatedAt": user.get("updatedAt"),
        "lastLoginAt": user.get("lastLoginAt"),
        "passwordExpiresAt": user.get("passwordExpiresAt"),
        "blocked": bool(user.get("blocked")),
        "blockedAt": user.get("blockedAt"),
        "blockedReason": user.get("blockedReason"),
        "organizationName": user.get("organizationName"),
        "organizationKey": user.get("organizationKey"),
        "organizationOwnerId": user.get("organizationOwnerId"),
        "createdByUserId": user.get("createdByUserId"),
        "invitationSentAt": user.get("invitationSentAt"),
        "invitationAcceptedAt": user.get("invitationAcceptedAt"),
        "invitationStatus": user.get("invitationStatus"),
        "inviteExpiresAt": user.get("inviteExpiresAt"),
        "isDemoAccount": bool(user.get("isDemoAccount")),
        "demoExpiresAt": user.get("demoExpiresAt"),
        "deletionRequested": bool(user.get("deletionRequested")),
        "mfaEnabled": bool(user.get("mfaEnabled")),
        "mfaConfiguredAt": user.get("mfaConfiguredAt"),
        "mfa": _sanitize_mfa(user.get("mfa")),
        "permissions": user.get("permissions") or {},
    }


def get_user_by_id(user_id: str) -> dict | None:
    purge_expired_demo_organizations()
    with get_session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        return map_user_document(user)


def find_user_by_email(email: str) -> dict | None:
    purge_expired_demo_organizations()
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
            encrypted_secret=json.dumps(setup["encryptedSecret"]),
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
    purge_expired_demo_organizations()

    full_name = (payload.get("fullName") or "").strip()
    if not full_name:
        raise ValueError("Nome completo e obrigatorio.")

    organization_name = _normalize_organization_name(payload.get("organizationName"))
    if not organization_name:
        raise ValueError("Nome da organizacao e obrigatorio.")
    organization_key = _organization_key_from_name(organization_name)

    if not bool(payload.get("consent")):
        raise ValueError("Consentimento LGPD e obrigatorio.")

    normalized_email = _normalize_email(payload["email"])
    _validate_password(payload["password"])
    if find_user_by_email(normalized_email):
        raise ValueError("Esse e-mail já está sendo usado.")

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
            full_name=full_name,
            organization_name=organization_name,
            organization_key=organization_key,
            phone=(payload.get("phone") or "").strip() or None,
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
    purge_expired_demo_organizations()

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

    role = "Admin"
    now = _now_iso()
    demo_expires_at = (datetime.now(UTC) + timedelta(days=DEMO_TRIAL_DAYS)).isoformat()
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
            organization_name=challenge_dict.get("organizationName"),
            organization_key=challenge_dict.get("organizationKey"),
            organization_owner_id=user_id,
            is_demo_account=True,
            demo_expires_at=demo_expires_at,
            phone=challenge_dict.get("phone"),
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
    log_security_event(
        "user_registered",
        user_id=user_id,
        metadata={
            "email": challenge_dict["email"],
            "role": role,
            "organizationName": challenge_dict.get("organizationName"),
            "demoExpiresAt": demo_expires_at,
        },
    )
    return sanitize_user(created)


def login_user(payload: dict) -> dict:
    normalized_email = _normalize_email(payload["email"])
    user = find_user_by_email(normalized_email)
    if not user:
        log_security_event("login_failed", metadata={"reason": "unknown_email", "email": normalized_email}, ip_address=payload.get("ipAddress"))
        raise PermissionError("Usuário ou senha incorretos.")

    if bool(user.get("blocked")):
        log_security_event("login_blocked_user", user_id=user["id"], metadata={"reason": user.get("blockedReason")}, ip_address=payload.get("ipAddress"))
        raise PermissionError("Seu usuário está bloqueado. Contate o administrador da organização.")

    if not verify_password(payload["password"], user["passwordHash"]):
        log_security_event("login_failed", user_id=user["id"], metadata={"reason": "invalid_password"}, ip_address=payload.get("ipAddress"))
        raise PermissionError("Usuário ou senha incorretos.")

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

            encrypted_secret = _normalize_encrypted_secret(enrollment_dict.get("encryptedSecret"))
            if not encrypted_secret:
                raise ValueError("Segredo OTP invalido para este cadastro.")

            if not verify_totp_code_with_encrypted_secret(payload["code"], encrypted_secret):
                with get_session() as db:
                    db.query(OtpEnrollment).filter(OtpEnrollment.id == enrollment_id).update({"attempts": attempts + 1})
                raise PermissionError("Codigo do autenticador invalido.")

            now = _now_iso()
            mfa_config = {
                "enforcedMethods": ENFORCED_MFA_METHODS,
                "email": {"delivery": "email", "configuredAt": ((user.get("mfa") or {}).get("email") or {}).get("configuredAt") or user.get("createdAt") or now},
                "otp": {
                    "configuredAt": now,
                    "secret": encrypted_secret,
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

    encrypted_secret = _normalize_encrypted_secret(enrollment_dict.get("encryptedSecret"))
    if not encrypted_secret:
        raise ValueError("Segredo OTP invalido para este cadastro.")

    if not verify_totp_code_with_encrypted_secret(payload["code"], encrypted_secret):
        with get_session() as db:
            db.query(OtpEnrollment).filter(OtpEnrollment.id == payload["enrollmentId"]).update({"attempts": attempts + 1})
        raise PermissionError("Codigo do autenticador invalido.")

    now = _now_iso()
    mfa_config = {
        "enforcedMethods": ENFORCED_MFA_METHODS,
        "email": {"delivery": "email", "configuredAt": ((user.get("mfa") or {}).get("email") or {}).get("configuredAt") or user.get("createdAt") or now},
        "otp": {
            "configuredAt": now,
            "secret": encrypted_secret,
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

    if bool(user.get("blocked")):
        log_security_event("password_reset_blocked_user", user_id=user["id"], metadata={"email": normalized_email})
        raise PermissionError("Seu usuário está bloqueado. Contate o administrador da organização.")

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


def start_first_access(payload: dict) -> dict:
    token_hash = hash_token(payload["token"])
    with get_session() as db:
        record = db.query(Token).filter(
            Token.token_hash == token_hash,
            Token.token_type == "first_access",
        ).first()
        record_dict = record.to_dict() if record else None

    if not record_dict:
        raise ValueError("Token de primeiro acesso invalido.")
    if record_dict.get("revoked"):
        raise ValueError("Token de primeiro acesso ja utilizado.")
    if _is_expired(record_dict.get("expiresAt")):
        raise PermissionError("Token de primeiro acesso expirado.")

    user = get_user_by_id(record_dict["userId"])
    if not user:
        raise FileNotFoundError("Usuario nao encontrado.")
    if bool(user.get("blocked")):
        raise PermissionError("Seu usuário está bloqueado. Contate o administrador da organização.")

    enrollment = _create_otp_enrollment_for_user(user)
    log_security_event(
        "first_access_started",
        user_id=user["id"],
        metadata={
            "enrollmentId": enrollment["enrollmentId"],
            "tokenExpiresAt": record_dict.get("expiresAt"),
        },
        ip_address=payload.get("ipAddress"),
    )

    return {
        "user": {
            "email": user.get("email"),
            "fullName": user.get("fullName"),
            "role": _normalize_role(user.get("role")),
            "roleLabel": _role_label(_normalize_role(user.get("role"))),
        },
        "enrollment": enrollment,
        "tokenExpiresAt": record_dict.get("expiresAt"),
    }


def complete_first_access(payload: dict) -> dict:
    _validate_password(payload["newPassword"])

    token_hash = hash_token(payload["token"])
    with get_session() as db:
        record = db.query(Token).filter(
            Token.token_hash == token_hash,
            Token.token_type == "first_access",
        ).first()
        record_dict = record.to_dict() if record else None

    if not record_dict:
        raise ValueError("Token de primeiro acesso invalido.")
    if record_dict.get("revoked"):
        raise ValueError("Token de primeiro acesso ja utilizado.")
    if _is_expired(record_dict.get("expiresAt")):
        raise PermissionError("Token de primeiro acesso expirado.")

    user = get_user_by_id(record_dict["userId"])
    if not user:
        raise FileNotFoundError("Usuario nao encontrado.")
    if bool(user.get("blocked")):
        raise PermissionError("Seu usuário está bloqueado. Contate o administrador da organização.")

    with get_session() as db:
        enrollment = db.query(OtpEnrollment).filter(OtpEnrollment.id == payload["enrollmentId"]).first()
        enrollment_dict = enrollment.to_dict() if enrollment else None

    if not enrollment_dict or enrollment_dict.get("userId") != user["id"]:
        raise FileNotFoundError("Configuracao de autenticador invalida ou expirada.")

    if _is_expired(enrollment_dict.get("expiresAt")):
        with get_session() as db:
            db.query(OtpEnrollment).filter(OtpEnrollment.id == payload["enrollmentId"]).delete(synchronize_session=False)
        raise PermissionError("Configuracao de autenticador expirada. Reinicie o primeiro acesso.")

    attempts = int(enrollment_dict.get("attempts", 0))
    if attempts >= OTP_ENROLLMENT_MAX_ATTEMPTS:
        with get_session() as db:
            db.query(OtpEnrollment).filter(OtpEnrollment.id == payload["enrollmentId"]).delete(synchronize_session=False)
        raise PermissionError("Configuracao de autenticador bloqueada por tentativas invalidas.")

    encrypted_secret = _normalize_encrypted_secret(enrollment_dict.get("encryptedSecret"))
    if not encrypted_secret:
        raise ValueError("Segredo OTP invalido para este cadastro.")

    if not verify_totp_code_with_encrypted_secret(payload["otpCode"], encrypted_secret):
        with get_session() as db:
            db.query(OtpEnrollment).filter(OtpEnrollment.id == payload["enrollmentId"]).update({"attempts": attempts + 1})
        raise PermissionError("Codigo do autenticador invalido.")

    now = _now_iso()
    mfa_config = {
        "enforcedMethods": ENFORCED_MFA_METHODS,
        "email": {
            "delivery": "email",
            "configuredAt": ((user.get("mfa") or {}).get("email") or {}).get("configuredAt") or user.get("createdAt") or now,
        },
        "otp": {
            "configuredAt": now,
            "secret": encrypted_secret,
            "issuer": enrollment_dict.get("issuer") or settings.mfa_issuer,
            "accountName": enrollment_dict.get("accountName") or user["email"],
        },
    }

    with get_session() as db:
        u = db.query(User).filter(User.id == user["id"]).first()
        if u:
            u.password_hash = hash_password(payload["newPassword"])
            u.last_password_change = now
            u.password_expires_at = calculate_password_expiry_iso()
            u.mfa_enabled = True
            u.mfa_configured_at = now
            u.mfa_config = mfa_config
            u.invitation_accepted_at = now

        db.query(OtpEnrollment).filter(OtpEnrollment.id == payload["enrollmentId"]).delete(synchronize_session=False)
        db.query(Token).filter(
            Token.user_id == user["id"],
            Token.token_type == "first_access",
            Token.revoked.is_(False),
        ).update({"revoked": True, "revoked_at": now}, synchronize_session=False)

    refreshed_user = get_user_by_id(user["id"])
    log_security_event(
        "first_access_completed",
        user_id=user["id"],
        metadata={"enrollmentId": payload["enrollmentId"]},
        ip_address=payload.get("ipAddress"),
    )
    return sanitize_user(refreshed_user)


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
    if bool(user.get("blocked")):
        raise PermissionError("Seu usuário está bloqueado. Contate o administrador da organização.")

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

    organization_name_raw = payload.get("organizationName")
    organization_name = _normalize_organization_name(organization_name_raw) if organization_name_raw is not None else None
    should_update_org = bool(organization_name)

    if should_update_org and _normalize_role(user.get("role")) != "Admin":
        raise PermissionError("Apenas administradores podem alterar o nome da organizacao.")

    owner_id, _ = _organization_scope(user)
    if should_update_org and owner_id != user.get("id"):
        raise PermissionError("Somente o administrador principal pode alterar o nome da organizacao.")

    consent = bool(payload.get("consentGiven"))
    updated_org = False
    with get_session() as db:
        u = db.query(User).filter(User.id == payload["userId"]).first()
        if u:
            u.full_name = (payload.get("fullName") or "").strip() or None
            u.phone = None  # removido do produto
            u.consent_given = consent
            if consent and not u.consent_timestamp:
                u.consent_timestamp = _now_iso()

        if should_update_org:
            org_key = _organization_key_from_name(organization_name)
            resolved_owner_id = owner_id or payload["userId"]
            organization_users = db.query(User).filter(
                or_(User.organization_owner_id == resolved_owner_id, User.id == resolved_owner_id)
            ).all()
            if not organization_users and u:
                organization_users = [u]

            for member in organization_users:
                member.organization_name = organization_name
                member.organization_key = org_key
                if not member.organization_owner_id:
                    member.organization_owner_id = resolved_owner_id
            updated_org = len(organization_users) > 0

    log_security_event(
        "user_profile_updated",
        user_id=payload["userId"],
        metadata={
            "consentGiven": consent,
            "organizationUpdated": updated_org,
        },
    )
    return get_user_profile(payload["userId"])


def list_users(actor_user_id: str) -> list[dict]:
    actor = get_user_by_id(actor_user_id)
    if not actor or _normalize_role(actor.get("role")) != "Admin":
        raise PermissionError("Apenas administradores podem listar usuarios.")

    owner_id, org_key = _organization_scope(actor)
    with get_session() as db:
        query = db.query(User)
        if owner_id:
            query = query.filter(or_(User.organization_owner_id == owner_id, User.id == actor_user_id))
        elif org_key:
            query = query.filter(User.organization_key == org_key)
        else:
            query = query.filter(User.id == actor_user_id)
        users = query.order_by(User.created_at.desc()).all()
        user_ids = [u.id for u in users]

        latest_invites: dict[str, Token] = {}
        if user_ids:
            invite_rows = (
                db.query(Token)
                .filter(
                    Token.user_id.in_(user_ids),
                    Token.token_type == "first_access",
                )
                .order_by(Token.created_at.desc())
                .all()
            )
            for row in invite_rows:
                if row.user_id not in latest_invites:
                    latest_invites[row.user_id] = row

        response: list[dict] = []
        for item in users:
            payload = item.to_dict()
            invite_token = latest_invites.get(item.id)
            invite_expires_at = invite_token.expires_at if invite_token else None

            invitation_status = None
            if payload.get("invitationAcceptedAt"):
                invitation_status = "accepted"
            elif payload.get("createdByUserId") or payload.get("invitationSentAt") or invite_token:
                if invite_token and not bool(invite_token.revoked) and not _is_expired(invite_token.expires_at):
                    invitation_status = "pending"
                else:
                    invitation_status = "expired"

            payload["invitationStatus"] = invitation_status
            payload["inviteExpiresAt"] = invite_expires_at
            response.append(sanitize_user(payload))

        return response


def update_user_role(payload: dict) -> dict:
    actor = get_user_by_id(payload["actorUserId"])
    if not actor or actor.get("role") != "Admin":
        raise PermissionError("Apenas administradores podem alterar perfis de acesso.")

    if payload["actorUserId"] == payload["targetUserId"]:
        raise PermissionError("Nao e permitido alterar a propria permissao.")

    target = get_user_by_id(payload["targetUserId"])
    if not target:
        raise FileNotFoundError("Usuario alvo nao encontrado.")
    if not _same_organization(actor, target):
        raise PermissionError("Nao e permitido alterar usuarios de outra organizacao.")

    normalized_role = _normalize_role(payload.get("role"))
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


def create_user_by_admin(payload: dict) -> dict:
    purge_expired_demo_organizations()

    actor = get_user_by_id(payload["actorUserId"])
    if not actor or _normalize_role(actor.get("role")) != "Admin":
        raise PermissionError("Apenas administradores podem criar usuarios.")

    full_name = (payload.get("fullName") or "").strip()
    email = _normalize_email(payload.get("email") or "")
    if not full_name:
        raise ValueError("Nome completo e obrigatorio.")
    if not email:
        raise ValueError("E-mail e obrigatorio.")
    existing_user = find_user_by_email(email)
    if existing_user:
        if _same_organization(actor, existing_user):
            raise ValueError("Este usuario ja faz parte da sua organizacao.")
        raise ValueError("Este usuario ja faz parte de outra organizacao e precisa apagar o acesso atual antes de receber convite nesta organizacao.")

    role = _normalize_role(payload.get("role"))
    reader_greenhouse_ids = payload.get("readerGreenhouseIds") if isinstance(payload.get("readerGreenhouseIds"), list) else []
    now = _now_iso()
    user_id = str(uuid4())
    actor_owner_id, actor_org_key = _organization_scope(actor)
    actor_org_name = _normalize_organization_name(actor.get("organizationName"))
    demo_expires_at = actor.get("demoExpiresAt") if bool(actor.get("isDemoAccount")) else None

    # senha aleatória; o usuário define a própria pelo link de convite
    temp_password = secrets.token_urlsafe(32) + "Aa1!"

    with get_session() as db:
        db.add(
            User(
                id=user_id,
                email=email,
                role=role,
                password_hash=hash_password(temp_password),
                full_name=full_name,
                phone=None,
                organization_name=actor_org_name,
                organization_key=actor_org_key,
                organization_owner_id=actor_owner_id,
                created_by_user_id=payload["actorUserId"],
                invitation_sent_at=now,
                invitation_accepted_at=None,
                is_demo_account=bool(actor.get("isDemoAccount")),
                demo_expires_at=demo_expires_at,
                permissions={"allowedGreenhouseIds": reader_greenhouse_ids} if role == "Reader" else {},
                consent_given=False,
                consent_timestamp=None,
                last_login_at=None,
                last_password_change=now,
                password_expires_at=now,
                blocked=False,
                blocked_at=None,
                blocked_reason=None,
                deletion_requested=False,
                mfa_enabled=False,
                mfa_configured_at=None,
                mfa_config=None,
            )
        )

    raw_token = secrets.token_hex(48)
    token_hash = hash_token(raw_token)
    expires_at = (datetime.now(UTC) + timedelta(seconds=settings.password_reset_ttl_seconds)).isoformat()

    with get_session() as db:
        db.add(
            Token(
                id=str(uuid4()),
                user_id=user_id,
                token_hash=token_hash,
                token_type="first_access",
                expires_at=expires_at,
                revoked=False,
            )
        )

    invite_link = f"{settings.resolved_frontend_public_url}/login?firstAccessToken={raw_token}"
    smtp_configured = bool(settings.smtp_user and settings.smtp_password and settings.resolved_smtp_from)
    invitation_sent = False

    if smtp_configured:
        try:
            send_user_invitation_email(
                to=email,
                invite_link=invite_link,
                expires_at=expires_at,
                role_label=_role_label(role),
            )
            invitation_sent = True
        except Exception as exc:
            log_security_event(
                "admin_user_invite_failed",
                user_id=payload["actorUserId"],
                metadata={"targetEmail": email, "reason": str(exc)},
            )

    created = get_user_by_id(user_id)
    log_security_event(
        "admin_user_created",
        user_id=payload["actorUserId"],
        metadata={"targetUserId": user_id, "targetEmail": email, "role": role, "inviteSent": invitation_sent},
    )

    return {
        "user": sanitize_user(created),
        "invitationSent": invitation_sent,
        "inviteExpiresAt": expires_at,
        "inviteLink": None if invitation_sent else invite_link,
    }


def resend_user_invitation(payload: dict) -> dict:
    actor = get_user_by_id(payload["actorUserId"])
    if not actor or _normalize_role(actor.get("role")) != "Admin":
        raise PermissionError("Apenas administradores podem reenviar convite.")

    target = get_user_by_id(payload["targetUserId"])
    if not target:
        raise FileNotFoundError("Usuario alvo nao encontrado.")
    if not _same_organization(actor, target):
        raise PermissionError("Nao e permitido reenviar convite para outra organizacao.")
    if target.get("id") == actor.get("id"):
        raise PermissionError("Nao e permitido reenviar convite para o proprio usuario.")
    if target.get("invitationAcceptedAt"):
        raise PermissionError("Este usuario ja aceitou o convite de primeiro acesso.")

    now = _now_iso()
    raw_token = secrets.token_hex(48)
    token_hash = hash_token(raw_token)
    expires_at = (datetime.now(UTC) + timedelta(seconds=settings.password_reset_ttl_seconds)).isoformat()

    with get_session() as db:
        db.query(Token).filter(
            Token.user_id == target["id"],
            Token.token_type == "first_access",
            Token.revoked.is_(False),
        ).update({"revoked": True, "revoked_at": now}, synchronize_session=False)

        db.add(
            Token(
                id=str(uuid4()),
                user_id=target["id"],
                token_hash=token_hash,
                token_type="first_access",
                expires_at=expires_at,
                revoked=False,
            )
        )

        u = db.query(User).filter(User.id == target["id"]).first()
        if u:
            u.invitation_sent_at = now

    invite_link = f"{settings.resolved_frontend_public_url}/login?firstAccessToken={raw_token}"
    smtp_configured = bool(settings.smtp_user and settings.smtp_password and settings.resolved_smtp_from)
    invitation_sent = False

    if smtp_configured:
        try:
            send_user_invitation_email(
                to=target["email"],
                invite_link=invite_link,
                expires_at=expires_at,
                role_label=_role_label(_normalize_role(target.get("role"))),
            )
            invitation_sent = True
        except Exception as exc:
            log_security_event(
                "admin_user_invite_failed",
                user_id=payload["actorUserId"],
                metadata={"targetEmail": target["email"], "reason": str(exc), "flow": "resend"},
            )

    log_security_event(
        "admin_user_invite_resent",
        user_id=payload["actorUserId"],
        metadata={"targetUserId": target["id"], "targetEmail": target["email"], "inviteSent": invitation_sent},
    )

    return {
        "invitationSent": invitation_sent,
        "inviteExpiresAt": expires_at,
        "inviteLink": None if invitation_sent else invite_link,
    }


def delete_user_by_admin(payload: dict) -> dict:
    # dados da org são reatribuídos ao criador
    actor = get_user_by_id(payload["actorUserId"])
    if not actor or _normalize_role(actor.get("role")) != "Admin":
        raise PermissionError("Apenas administradores podem remover usuarios.")

    target = get_user_by_id(payload["targetUserId"])
    if not target:
        raise FileNotFoundError("Usuario alvo nao encontrado.")
    if not _same_organization(actor, target):
        raise PermissionError("Nao e permitido remover usuarios de outra organizacao.")
    actor_is_owner = (actor.get("organizationOwnerId") or "").strip() == actor.get("id")
    if payload["actorUserId"] == payload["targetUserId"] and actor_is_owner:
        raise PermissionError("O usuario criador deve usar o fluxo de desativacao da organizacao.")
    if target.get("organizationOwnerId") == target.get("id"):
        raise PermissionError("Nao e permitido remover o usuario criador da organizacao.")

    owner_id = (target.get("organizationOwnerId") or "").strip()
    if not owner_id:
        raise PermissionError("Organizacao sem criador definido. Operacao bloqueada por seguranca.")

    with get_session() as db:
        db.query(Estufa).filter(Estufa.user_id == target["id"]).update({Estufa.user_id: owner_id}, synchronize_session=False)
        db.query(Historico).filter(Historico.user_id == target["id"]).update({Historico.user_id: owner_id}, synchronize_session=False)
        db.query(Alertas).filter(Alertas.user_id == target["id"]).update({Alertas.user_id: owner_id}, synchronize_session=False)
        db.query(Preset).filter(Preset.user_id == target["id"]).update({Preset.user_id: owner_id}, synchronize_session=False)
        db.query(Greenhouse).filter(Greenhouse.owner_id == target["id"]).update({Greenhouse.owner_id: owner_id}, synchronize_session=False)

        db.query(Token).filter(Token.user_id == target["id"]).delete(synchronize_session=False)
        db.query(LoginSession).filter(LoginSession.user_id == target["id"]).delete(synchronize_session=False)
        db.query(MfaChallenge).filter(MfaChallenge.user_id == target["id"]).delete(synchronize_session=False)
        db.query(OtpEnrollment).filter(OtpEnrollment.user_id == target["id"]).delete(synchronize_session=False)
        db.query(SecurityLog).filter(SecurityLog.user_id == target["id"]).update({SecurityLog.user_id: owner_id}, synchronize_session=False)
        db.query(User).filter(User.id == target["id"]).delete(synchronize_session=False)

    log_security_event(
        "admin_user_deleted",
        user_id=payload["actorUserId"],
        metadata={
            "targetUserId": payload["targetUserId"],
            "organizationOwnerId": owner_id,
            "dataPreserved": True,
        },
    )
    return {"deletedUserId": payload["targetUserId"], "dataReassignedToUserId": owner_id}


def deactivate_organization_by_owner(payload: dict) -> dict:
    actor = get_user_by_id(payload["actorUserId"])
    if not actor or _normalize_role(actor.get("role")) != "Admin":
        raise PermissionError("Apenas administradores podem desativar a organizacao.")

    owner_id = (actor.get("organizationOwnerId") or "").strip()
    if not owner_id or owner_id != actor.get("id"):
        raise PermissionError("Somente o usuario criador da organizacao pode desativar a organizacao inteira.")

    now = _now_iso()
    with get_session() as db:
        members = db.query(User).filter(or_(User.organization_owner_id == owner_id, User.id == owner_id)).all()
        member_ids = [m.id for m in members]
        deleted_legacy_greenhouses = 0
        deleted_modern_greenhouses = 0

        if member_ids:
            estufa_ids = [row[0] for row in db.query(Estufa.id).filter(Estufa.user_id.in_(member_ids)).all()]
            deleted_legacy_greenhouses = len(estufa_ids)
            modern_greenhouse_ids = [row[0] for row in db.query(Greenhouse.id).filter(Greenhouse.owner_id.in_(member_ids)).all()]
            deleted_modern_greenhouses = len(modern_greenhouse_ids)

            if estufa_ids:
                dispositivo_ids = [row[0] for row in db.query(Dispositivo.id).filter(Dispositivo.estufa_id.in_(estufa_ids)).all()]
                if dispositivo_ids:
                    db.query(Alertas).filter(Alertas.dispositivo_id.in_(dispositivo_ids)).delete(synchronize_session=False)
                    db.query(Historico).filter(Historico.dispositivo_id.in_(dispositivo_ids)).delete(synchronize_session=False)

                db.query(Alertas).filter(Alertas.estufa_id.in_(estufa_ids)).delete(synchronize_session=False)
                db.query(Historico).filter(Historico.estufa_id.in_(estufa_ids)).delete(synchronize_session=False)
                db.query(Dispositivo).filter(Dispositivo.estufa_id.in_(estufa_ids)).delete(synchronize_session=False)
                db.query(Estufa).filter(Estufa.id.in_(estufa_ids)).delete(synchronize_session=False)

            db.query(Alertas).filter(Alertas.user_id.in_(member_ids)).delete(synchronize_session=False)
            db.query(Historico).filter(Historico.user_id.in_(member_ids)).delete(synchronize_session=False)
            db.query(Preset).filter(
                Preset.user_id.in_(member_ids),
                Preset.sistema.is_(False),
            ).delete(synchronize_session=False)
            db.query(Greenhouse).filter(Greenhouse.owner_id.in_(member_ids)).delete(synchronize_session=False)
            db.query(SecurityLog).filter(SecurityLog.user_id.in_(member_ids)).update(
                {SecurityLog.user_id: None},
                synchronize_session=False,
            )

            db.query(Token).filter(Token.user_id.in_(member_ids)).update(
                {Token.revoked: True, Token.revoked_at: now},
                synchronize_session=False,
            )
            db.query(LoginSession).filter(LoginSession.user_id.in_(member_ids)).delete(synchronize_session=False)
            db.query(MfaChallenge).filter(MfaChallenge.user_id.in_(member_ids)).delete(synchronize_session=False)
            db.query(OtpEnrollment).filter(OtpEnrollment.user_id.in_(member_ids)).delete(synchronize_session=False)
            db.query(User).filter(User.id.in_(member_ids)).delete(synchronize_session=False)

    log_security_event(
        "organization_deactivated_by_owner",
        user_id=payload["actorUserId"],
        metadata={
            "organizationOwnerId": owner_id,
            "affectedUsers": len(member_ids),
            "dataDeleted": True,
            "deletedLegacyGreenhouses": deleted_legacy_greenhouses,
            "deletedModernGreenhouses": deleted_modern_greenhouses,
        },
    )
    return {
        "affectedUsers": len(member_ids),
        "organizationOwnerId": owner_id,
        "deletedLegacyGreenhouses": deleted_legacy_greenhouses,
        "deletedModernGreenhouses": deleted_modern_greenhouses,
    }


def set_user_access_status(payload: dict) -> dict:
    actor = get_user_by_id(payload["actorUserId"])
    if not actor or _normalize_role(actor.get("role")) != "Admin":
        raise PermissionError("Apenas administradores podem alterar status de acesso.")

    if payload["actorUserId"] == payload["targetUserId"]:
        raise PermissionError("Nao e permitido alterar o proprio status de acesso.")

    target = get_user_by_id(payload["targetUserId"])
    if not target:
        raise FileNotFoundError("Usuario alvo nao encontrado.")
    if not _same_organization(actor, target):
        raise PermissionError("Nao e permitido alterar usuarios de outra organizacao.")

    blocked = bool(payload.get("blocked"))
    reason = (payload.get("reason") or "").strip() or None

    with get_session() as db:
        u = db.query(User).filter(User.id == payload["targetUserId"]).first()
        if u:
            u.blocked = blocked
            u.blocked_reason = reason if blocked else None
            u.blocked_at = _now_iso() if blocked else None

    updated = get_user_by_id(payload["targetUserId"])
    log_security_event(
        "user_access_status_updated",
        user_id=payload["actorUserId"],
        metadata={"targetUserId": payload["targetUserId"], "blocked": blocked, "reason": reason},
    )
    return sanitize_user(updated)


def update_reader_greenhouse_access(payload: dict) -> dict:
    actor = get_user_by_id(payload["actorUserId"])
    if not actor or _normalize_role(actor.get("role")) != "Admin":
        raise PermissionError("Apenas administradores podem definir acesso de leitor.")

    if payload["actorUserId"] == payload["targetUserId"]:
        raise PermissionError("Nao e permitido alterar a propria permissao.")

    target = get_user_by_id(payload["targetUserId"])
    if not target:
        raise FileNotFoundError("Usuario alvo nao encontrado.")
    if not _same_organization(actor, target):
        raise PermissionError("Nao e permitido alterar usuarios de outra organizacao.")

    if _normalize_role(target.get("role")) != "Reader":
        raise PermissionError("A delegacao de estufas se aplica apenas ao perfil Leitor.")

    allowed_ids = payload.get("allowedGreenhouseIds") or []
    if not isinstance(allowed_ids, list):
        raise ValueError("allowedGreenhouseIds deve ser uma lista.")

    cleaned_ids: list[str] = []
    seen: set[str] = set()
    for item in allowed_ids:
        value = str(item or "").strip()
        if value and value not in seen:
            seen.add(value)
            cleaned_ids.append(value)

    with get_session() as db:
        u = db.query(User).filter(User.id == payload["targetUserId"]).first()
        if u:
            # novo dict necessário; SQLAlchemy não detecta mutação in-place em JSON
            permissions = dict(u.permissions or {})
            permissions["allowedGreenhouseIds"] = cleaned_ids
            u.permissions = permissions

    updated = get_user_by_id(payload["targetUserId"])
    log_security_event(
        "reader_greenhouse_access_updated",
        user_id=payload["actorUserId"],
        metadata={"targetUserId": payload["targetUserId"], "allowedGreenhouseIds": cleaned_ids},
    )
    return sanitize_user(updated)
