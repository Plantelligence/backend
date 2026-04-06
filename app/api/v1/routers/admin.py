# rotas de admin: usuários, papéis e bloqueio

# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from sqlalchemy import or_

from app.core.dependencies import require_role
from app.db.postgres.session import get_session
from app.models.estufa import Estufa
from app.models.user import User
from app.services.auth_service import (
    create_user_by_admin,
    deactivate_organization_by_owner,
    delete_user_by_admin,
    get_user_by_id,
    list_users,
    resend_user_invitation,
    set_user_access_status,
    update_reader_greenhouse_access,
    update_user_role,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

JsonDict = dict[str, Any]


class UpdateRoleRequest(BaseModel):
    role: str


class CreateUserRequest(BaseModel):
    fullName: str
    email: str
    role: str = "Collaborator"
    readerGreenhouseIds: list[str] = []


class UpdateAccessStatusRequest(BaseModel):
    blocked: bool
    reason: str | None = None


class UpdateReaderAccessRequest(BaseModel):
    greenhouseIds: list[str]


def _list_all_greenhouses(actor: JsonDict) -> list[JsonDict]:
    actor_id = str(actor.get("id") or "").strip()
    owner_id = str(actor.get("organizationOwnerId") or actor_id).strip()
    org_key = str(actor.get("organizationKey") or "").strip()

    with get_session() as db:
        query = db.query(
            Estufa.id,
            Estufa.nome,
            Estufa.cidade,
            Estufa.estado,
            Estufa.user_id,
        ).join(User, User.id == Estufa.user_id)
        if owner_id:
            query = query.filter(or_(User.organization_owner_id == owner_id, User.id == actor_id))
        elif org_key:
            query = query.filter(User.organization_key == org_key)
        else:
            query = query.filter(Estufa.user_id == actor_id)
        rows = query.order_by(Estufa.nome.asc()).all()
        # colunas projetadas; sem instâncias ORM para não explodir fora da sessão
        return [
            {
                "id": item[0],
                "nome": item[1],
                "cidade": item[2],
                "estado": item[3],
                "userId": item[4],
            }
            for item in rows
        ]


@router.get("/users")
async def users(actor: JsonDict = Depends(require_role("Admin"))) -> JsonDict:
    try:
        return {"users": list_users(actor["id"])}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(payload: CreateUserRequest, actor: JsonDict = Depends(require_role("Admin"))) -> JsonDict:
    try:
        result = create_user_by_admin(
            {
                "actorUserId": actor["id"],
                "fullName": payload.fullName,
                "email": payload.email,
                "role": payload.role,
                "readerGreenhouseIds": payload.readerGreenhouseIds,
            }
        )
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.put("/users/{user_id}/role")
async def user_role(user_id: str, payload: UpdateRoleRequest, actor: JsonDict = Depends(require_role("Admin"))) -> JsonDict:
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
async def admin_user_greenhouses(user_id: str, actor: JsonDict = Depends(require_role("Admin"))) -> JsonDict:
    # mantido por compatibilidade; devolve estufas delegadas ao leitor
    try:
        user = get_user_by_id(user_id)
        if not user:
            raise FileNotFoundError("Usuario nao encontrado.")

        allowed_ids = ((user.get("permissions") or {}).get("allowedGreenhouseIds") or [])
        all_greenhouses = _list_all_greenhouses(actor)
        delegated = [g for g in all_greenhouses if g["id"] in allowed_ids]
        return {"greenhouses": delegated}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/greenhouses")
async def admin_greenhouses(actor: JsonDict = Depends(require_role("Admin"))) -> JsonDict:
    try:
        return {"greenhouses": _list_all_greenhouses(actor)}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.put("/users/{user_id}/access-status")
async def admin_update_access_status(user_id: str, payload: UpdateAccessStatusRequest, actor: JsonDict = Depends(require_role("Admin"))) -> JsonDict:
    try:
        user = set_user_access_status(
            {
                "actorUserId": actor["id"],
                "targetUserId": user_id,
                "blocked": payload.blocked,
                "reason": payload.reason,
            }
        )
        return {"user": user}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/users/{user_id}/reader-greenhouses")
async def admin_update_reader_greenhouses(user_id: str, payload: UpdateReaderAccessRequest, actor: JsonDict = Depends(require_role("Admin"))) -> JsonDict:
    try:
        user = update_reader_greenhouse_access(
            {
                "actorUserId": actor["id"],
                "targetUserId": user_id,
                "allowedGreenhouseIds": payload.greenhouseIds,
            }
        )
        return {"user": user}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/users/{user_id}/resend-invite")
async def admin_resend_invite(user_id: str, actor: JsonDict = Depends(require_role("Admin"))) -> JsonDict:
    try:
        return resend_user_invitation({"actorUserId": actor["id"], "targetUserId": user_id})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/users/{user_id}")
async def admin_delete_user(user_id: str, actor: JsonDict = Depends(require_role("Admin"))) -> JsonDict:
    # dados da org são reatribuídos ao criador, não excluídos
    try:
        return delete_user_by_admin({"actorUserId": actor["id"], "targetUserId": user_id})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/organization/deactivate")
async def admin_deactivate_organization(actor: JsonDict = Depends(require_role("Admin"))) -> JsonDict:
    # só o criador da org pode usar esta rota
    try:
        return deactivate_organization_by_owner({"actorUserId": actor["id"]})
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
