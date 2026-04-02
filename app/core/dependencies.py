"""Dependencias de autenticacao/autorizacao para FastAPI."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services import auth_service
from app.services.token_service import verify_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def _raise_unauthorized(message: str = "Token invalido ou expirado.") -> None:
    """Lanca resposta 401 padronizada para falhas de autenticacao."""
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    """Valida JWT de acesso e carrega contexto basico de usuario."""

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

    return request.state.user


def require_role(*allowed_roles: str):
    """Factory de dependencia para RBAC por papel."""

    def checker(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        """Permite acesso apenas quando o papel do usuario esta na lista."""
        if user.get("role") not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso nao autorizado.")
        return user

    return checker


def get_user_profile_or_404(user_id: str) -> dict[str, Any]:
    """Helper para carregar perfil com erro HTTP padronizado."""

    try:
        return auth_service.get_user_profile(user_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
