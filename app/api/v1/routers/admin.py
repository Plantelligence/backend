"""Rotas administrativas para usuarios, papeis e equipe de estufas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from sqlalchemy import func

from app.core.dependencies import require_role
from app.db.postgres.session import get_session
from app.models.user import User
from app.services.auth_service import get_user_by_id, list_users, update_user_role
from app.services.greenhouse_service import (
    get_greenhouse_for_admin,
    list_greenhouses_for_admin,
    update_greenhouse_team,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class UpdateRoleRequest(BaseModel):
    role: str


class UpdateTeamRequest(BaseModel):
    watcherIds: list[str]


# Permissoes granulares alem do papel Admin/User.
# O frontend envia o objeto completo e o backend persiste como JSON no campo users.permissions.
class UpdatePermissionsRequest(BaseModel):
    canViewTelemetry: bool = True
    canViewAlerts: bool = True
    canControlActuators: bool = False
    canEditGreenhouseParameters: bool = False
    canManageTeam: bool = False


def _resolve_greenhouse_for_admin_target(target_id: str) -> dict:
    """Resolve estufa por id direto ou por ownerId para compatibilidade de contrato."""

    try:
        return get_greenhouse_for_admin(target_id)
    except FileNotFoundError:
        pass

    greenhouses = list_greenhouses_for_admin(target_id)
    if not greenhouses:
        raise FileNotFoundError("Estufa nao encontrada.")
    return greenhouses[0]


@router.get("/secure-data")
async def secure_data(_: dict = Depends(require_role("Admin"))) -> dict:
    """Endpoint de diagnostico admin com metrica basica."""

    with get_session() as db:
        total_users = db.query(func.count(User.id)).scalar() or 0
    return {
        "message": "Acesso concedido apenas a administradores.",
        "metrics": {"totalUsers": total_users},
    }


@router.get("/smtp-test")
async def smtp_test(_: dict = Depends(require_role("Admin"))) -> dict:
    """Testa a conexao SMTP e retorna o resultado detalhado para diagnostico."""

    import asyncio
    from app.config.settings import settings

    smtp_configured = bool(settings.smtp_user and settings.smtp_password)

    if not smtp_configured:
        return {
            "ok": False,
            "configured": False,
            "error": "SMTP_USER ou SMTP_PASSWORD ausentes nas variaveis de ambiente.",
            "smtp_user": settings.smtp_user or "(vazio)",
            "smtp_host": settings.smtp_host,
            "smtp_port": settings.smtp_port,
        }

    def _try_connect():
        import smtplib
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(settings.smtp_user, settings.smtp_password)
            return {"ok": True, "error": None}
        except smtplib.SMTPAuthenticationError as exc:
            return {"ok": False, "error": f"Autenticacao falhou: {exc.smtp_code} {exc.smtp_error}"}
        except smtplib.SMTPConnectError as exc:
            return {"ok": False, "error": f"Falha ao conectar: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    result = await asyncio.to_thread(_try_connect)
    return {
        **result,
        "configured": True,
        "smtp_user": settings.smtp_user,
        "smtp_host": settings.smtp_host,
        "smtp_port": settings.smtp_port,
    }


@router.get("/users")
async def users(_: dict = Depends(require_role("Admin"))) -> dict:
    """Lista usuarios com dados sanitizados para painel admin."""

    try:
        return {"users": list_users()}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.put("/users/{user_id}/role")
async def user_role(user_id: str, payload: UpdateRoleRequest, actor: dict = Depends(require_role("Admin"))) -> dict:
    """Altera role de usuario (Admin/User)."""

    try:
        user = update_user_role({"actorUserId": actor["id"], "targetUserId": user_id, "role": payload.role})
        return {"user": user}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/users/{user_id}/greenhouses")
async def admin_user_greenhouses(user_id: str, _: dict = Depends(require_role("Admin"))) -> dict:
    """Lista estufas de um usuario no contexto administrativo."""

    try:
        return {"greenhouses": list_greenhouses_for_admin(user_id)}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/greenhouse/{target_id}")
async def admin_greenhouse(target_id: str, _: dict = Depends(require_role("Admin"))) -> dict:
    """Retorna config de estufa para painel admin (por greenhouseId ou userId)."""

    try:
        greenhouse = _resolve_greenhouse_for_admin_target(target_id)
        return {"config": greenhouse, "greenhouse": greenhouse}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/greenhouse/{target_id}/team")
async def admin_update_team(target_id: str, payload: UpdateTeamRequest, actor: dict = Depends(require_role("Admin"))) -> dict:
    """Atualiza equipe de alertas por greenhouseId ou userId no contexto admin."""

    try:
        greenhouse_target = _resolve_greenhouse_for_admin_target(target_id)
        greenhouse = update_greenhouse_team(
            {
                "actorUserId": actor["id"],
                "greenhouseId": greenhouse_target["id"],
                "watcherIds": payload.watcherIds,
            }
        )
        return {"config": greenhouse, "greenhouse": greenhouse}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# Permissoes granulares por usuario
_DEFAULT_PERMISSIONS = {
    "canViewTelemetry": True,
    "canViewAlerts": True,
    "canControlActuators": False,
    "canEditGreenhouseParameters": False,
    "canManageTeam": False,
}


@router.get("/users/{user_id}/permissions")
async def get_user_permissions(user_id: str, _: dict = Depends(require_role("Admin"))) -> dict:
    """Retorna permissoes granulares do usuario (merge com defaults)."""

    try:
        user = get_user_by_id(user_id)
        if not user:
            raise FileNotFoundError("Usuario nao encontrado.")
        permissions = {**_DEFAULT_PERMISSIONS, **(user.get("permissions") or {})}
        return {"permissions": permissions}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.put("/users/{user_id}/permissions")
async def update_user_permissions(user_id: str, payload: UpdatePermissionsRequest, _: dict = Depends(require_role("Admin"))) -> dict:
    """Persiste permissoes granulares do usuario."""

    try:
        user = get_user_by_id(user_id)
        if not user:
            raise FileNotFoundError("Usuario nao encontrado.")

        new_permissions = payload.model_dump()
        with get_session() as db:
            u = db.query(User).filter(User.id == user_id).first()
            if u:
                u.permissions = new_permissions

        updated = get_user_by_id(user_id)
        permissions = {**_DEFAULT_PERMISSIONS, **(updated.get("permissions") or {})}
        return {"permissions": permissions}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
