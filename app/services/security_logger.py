"""Servico de trilha de auditoria de seguranca com hash encadeado — PostgreSQL."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from app.db.postgres.session import get_session
from app.models.security_log import SecurityLog


def _normalize_metadata(metadata: dict | None) -> dict:
    value = metadata or {}
    return {key: entry for key, entry in value.items() if entry is not None}


def log_security_event(
    action: str,
    user_id: str | None = None,
    metadata: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Registra evento de seguranca com hash corrente e hash anterior."""

    if not action:
        raise ValueError("Action is required to log security events.")

    with get_session() as db:
        last = db.query(SecurityLog).order_by(SecurityLog.created_at.desc()).first()
        prev_hash = last.hash if last else "GENESIS"

        now = datetime.now(UTC).isoformat()
        normalized = _normalize_metadata(metadata)
        payload = json.dumps(
            {
                "userId": user_id,
                "action": action,
                "metadata": normalized,
                "ipAddress": ip_address,
                "createdAt": now,
            },
            sort_keys=True,
        )
        hash_value = hashlib.sha256(f"{prev_hash}{payload}".encode("utf-8")).hexdigest()

        db.add(SecurityLog(
            id=str(uuid4()),
            user_id=user_id,
            action=action,
            log_metadata=normalized,
            ip_address=ip_address,
            hash=hash_value,
            prev_hash=prev_hash,
        ))


def get_security_logs(limit: int = 100, user_id: str | None = None) -> list[dict]:
    """Retorna ultimos eventos de seguranca para auditoria.

    Args:
        limit: Numero maximo de registros.
        user_id: Se informado, filtra apenas eventos do usuario. None = todos (admin).
    """

    with get_session() as db:
        q = db.query(SecurityLog).order_by(SecurityLog.created_at.desc())
        if user_id:
            q = q.filter(SecurityLog.user_id == user_id)
        return [log.to_dict() for log in q.limit(limit).all()]
