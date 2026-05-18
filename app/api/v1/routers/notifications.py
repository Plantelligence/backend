"""
Rotas REST para gerenciamento de notificacoes e preferencias.

Endpoints disponiveis:
  GET    /api/notifications                      — lista notificacoes do usuario (paginado)
  GET    /api/notifications/unread-count         — contagem de nao lidas
  PATCH  /api/notifications/{id}/read            — marcar como lida
  PATCH  /api/notifications/read-all             — marcar todas como lidas
  DELETE /api/notifications/{id}                 — descartar notificacao
  GET    /api/notifications/preferences          — preferencias atuais
  PUT    /api/notifications/preferences          — atualizar preferencias
  GET    /api/estufas/{id}/alertas               — historico de alertas da estufa
  GET    /api/estufas/{id}/alertas/resumo        — resumo: total, criticas, nao lidas

O frontend consulta via polling REST (sem WebSockets).
Recomendacao: polling a cada 30-60 segundos para /unread-count.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.estufa import Estufa
from app.models.notification import Notification
from app.models.notification_preference import NotificationPreference
from app.schemas.notification import (
    NotificationListResponse,
    NotificationPreferenceResponse,
    NotificationResponse,
    UpdateNotificationPreferenceRequest,
)

router = APIRouter(prefix="/api/notifications", tags=["Notificacoes"])


def _get_estufa_acessivel(estufa_id: str, user: dict[str, Any], db: Session) -> Estufa:
    """Verifica se o usuario tem acesso a estufa."""
    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    if not estufa:
        raise HTTPException(status_code=404, detail="Estufa nao encontrada.")
    responsaveis = estufa.responsible_user_ids or []
    tem_acesso = (
        estufa.user_id == user["id"]
        or user["id"] in responsaveis
        or user.get("role") == "Admin"
    )
    if not tem_acesso:
        raise HTTPException(status_code=403, detail="Acesso negado a esta estufa.")
    return estufa


# ── Listagem de notificacoes ───────────────────────────────────────────────

@router.get("/")
async def list_notifications(
    type: str | None = Query(default=None, description="Filtrar por tipo"),
    severity: str | None = Query(default=None, description="Filtrar por severidade"),
    greenhouse_id: str | None = Query(default=None, description="Filtrar por estufa"),
    read: bool | None = Query(default=None, description="Filtrar por estado de leitura"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lista notificacoes do usuario autenticado com filtros e paginacao."""
    query = (
        db.query(Notification)
        .filter(Notification.user_id == user["id"])
        .filter(Notification.dismissed_at.is_(None))
    )

    if type:
        query = query.filter(Notification.notification_type == type)
    if severity:
        query = query.filter(Notification.severity == severity)
    if greenhouse_id:
        query = query.filter(Notification.greenhouse_id == greenhouse_id)
    if read is not None:
        query = query.filter(Notification.read == read)

    # contagem total
    total = query.count()

    # contagem de nao lidas (independente dos filtros)
    unread_count = (
        db.query(Notification)
        .filter(Notification.user_id == user["id"])
        .filter(Notification.read.is_(False))
        .filter(Notification.dismissed_at.is_(None))
        .count()
    )

    rows = (
        query
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "notifications": [NotificationResponse.model_validate(r) for r in rows],
        "total": total,
        "unread_count": unread_count,
    }


@router.get("/unread-count")
async def unread_count(
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retorna apenas a contagem de notificacoes nao lidas. Ideal para polling."""
    count = (
        db.query(Notification)
        .filter(Notification.user_id == user["id"])
        .filter(Notification.read.is_(False))
        .filter(Notification.dismissed_at.is_(None))
        .count()
    )
    return {"count": count}


# ── Acoes em notificacoes ──────────────────────────────────────────────────

@router.patch("/{notification_id}/read")
async def mark_as_read(
    notification_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Marca uma notificacao como lida."""
    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.user_id == user["id"],
        )
        .first()
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Notificacao nao encontrada.")

    notification.read = True
    notification.read_at = datetime.now(timezone.utc).isoformat()
    db.commit()

    return {"message": "Notificacao marcada como lida."}


@router.patch("/read-all")
async def mark_all_as_read(
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Marca todas as notificacoes do usuario como lidas."""
    now_iso = datetime.now(timezone.utc).isoformat()
    (
        db.query(Notification)
        .filter(
            Notification.user_id == user["id"],
            Notification.read.is_(False),
            Notification.dismissed_at.is_(None),
        )
        .update({
            Notification.read: True,
            Notification.read_at: now_iso,
        })
    )
    db.commit()

    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user["id"])
        .filter(Notification.read.is_(True))
        .filter(Notification.read_at == now_iso)
        .count()
    )

    return {"message": f"{updated} notificacoes marcadas como lidas."}


@router.delete("/{notification_id}")
async def dismiss_notification(
    notification_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Descarta uma notificacao (soft delete)."""
    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.user_id == user["id"],
        )
        .first()
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Notificacao nao encontrada.")

    notification.dismissed_at = datetime.now(timezone.utc).isoformat()
    db.commit()

    return {"message": "Notificacao descartada."}


# ── Preferencias ───────────────────────────────────────────────────────────

@router.get("/preferences")
async def get_preferences(
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retorna as preferencias de notificacao do usuario."""
    prefs = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user["id"])
        .first()
    )

    if not prefs:
        # retornar padroes
        return {
            "id": None,
            "userId": user["id"],
            "channelEmail": True,
            "channelInapp": True,
            "blockedTypes": [],
            "quietHoursStart": None,
            "quietHoursEnd": None,
            "quietHoursIncludeWarning": False,
        }

    return NotificationPreferenceResponse.model_validate(prefs)


@router.put("/preferences")
async def update_preferences(
    payload: UpdateNotificationPreferenceRequest,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Atualiza as preferencias de notificacao do usuario."""
    prefs = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user["id"])
        .first()
    )

    if not prefs:
        prefs = NotificationPreference(
            user_id=user["id"],
            channel_email=True,
            channel_inapp=True,
            blocked_types=[],
            quiet_hours_start=None,
            quiet_hours_end=None,
            quiet_hours_include_warning=False,
        )
        db.add(prefs)

    # atualizar apenas campos informados
    if payload.channelEmail is not None:
        prefs.channel_email = payload.channelEmail
    if payload.channelInapp is not None:
        prefs.channel_inapp = payload.channelInapp
    if payload.blockedTypes is not None:
        prefs.blocked_types = payload.blockedTypes
    if payload.quietHoursStart is not None:
        prefs.quiet_hours_start = payload.quietHoursStart
    if payload.quietHoursEnd is not None:
        prefs.quiet_hours_end = payload.quietHoursEnd
    if payload.quietHoursIncludeWarning is not None:
        prefs.quiet_hours_include_warning = payload.quietHoursIncludeWarning

    db.commit()
    db.refresh(prefs)

    return NotificationPreferenceResponse.model_validate(prefs)


# ── Alertas por estufa ─────────────────────────────────────────────────────

@router.get("/estufas/{estufa_id}/alertas")
async def estufa_alertas(
    estufa_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Historico de alertas de uma estufa especifica."""
    _get_estufa_acessivel(estufa_id, user, db)

    rows = (
        db.query(Notification)
        .filter(
            Notification.greenhouse_id == estufa_id,
            Notification.dismissed_at.is_(None),
        )
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )

    return [NotificationResponse.model_validate(r) for r in rows]


@router.get("/estufas/{estufa_id}/alertas/resumo")
async def estufa_alertas_resumo(
    estufa_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resumo de alertas de uma estufa: total, criticas, nao lidas."""
    _get_estufa_acessivel(estufa_id, user, db)

    total = (
        db.query(Notification)
        .filter(
            Notification.greenhouse_id == estufa_id,
            Notification.dismissed_at.is_(None),
        )
        .count()
    )

    critical = (
        db.query(Notification)
        .filter(
            Notification.greenhouse_id == estufa_id,
            Notification.severity == "critical",
            Notification.dismissed_at.is_(None),
        )
        .count()
    )

    unread = (
        db.query(Notification)
        .filter(
            Notification.greenhouse_id == estufa_id,
            Notification.read.is_(False),
            Notification.dismissed_at.is_(None),
        )
        .count()
    )

    return {
        "greenhouseId": estufa_id,
        "total": total,
        "critical": critical,
        "unread": unread,
    }
