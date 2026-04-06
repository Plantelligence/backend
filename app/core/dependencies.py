# dependências de autenticação e autorização do FastAPI

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.postgres.session import SessionLocal
from app.services import auth_service
from app.services.token_service import verify_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _raise_unauthorized(message: str = "Token invalido ou expirado.") -> None:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    if not credentials or credentials.scheme.lower() != "bearer":
        _raise_unauthorized("Token de acesso ausente.")

    try:
        payload = verify_access_token(credentials.credentials)
    except Exception as exc:
        _raise_unauthorized(str(exc))

    request.state.user = {
        "id": payload.get("sub"),
        "email": payload.get("email"),
        "role": payload.get("role"),
        "tokenJti": payload.get("jti"),
        "requiresPasswordReset": payload.get("requiresPasswordReset", False),
    }

    if not request.state.user.get("id"):
        _raise_unauthorized()

    # revalida no banco a cada request — bloqueia imediatamente se o admin suspendeu a conta
    try:
        profile = auth_service.get_user_profile(request.state.user["id"])
    except Exception:
        _raise_unauthorized()

    if bool(profile.get("blocked")):
        _raise_unauthorized("Seu usuário está bloqueado. Contate o administrador da organização.")

    request.state.user["role"] = profile.get("role")
    request.state.user["permissions"] = profile.get("permissions") or {}
    request.state.user["organizationName"] = profile.get("organizationName")
    request.state.user["organizationOwnerId"] = profile.get("organizationOwnerId")
    request.state.user["organizationKey"] = profile.get("organizationKey")
    request.state.user["isDemoAccount"] = bool(profile.get("isDemoAccount"))
    request.state.user["demoExpiresAt"] = profile.get("demoExpiresAt")

    return request.state.user


def require_role(*allowed_roles: str):
    def checker(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user.get("role") not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso nao autorizado.")
        return user

    return checker


def get_user_profile_or_404(user_id: str) -> dict[str, Any]:
    try:
        return auth_service.get_user_profile(user_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
