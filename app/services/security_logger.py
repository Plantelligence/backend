# trilha de auditoria com hash encadeado (blockchain-lite) em PostgreSQL

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from app.db.postgres.session import get_session
from app.models.estufa import Estufa
from app.models.security_log import SecurityLog
from app.models.user import User


ADMIN_RELEVANT_ACTIONS = {
    "login_success",
    "session_revoked",
    "password_changed",
    "mfa_totp_enrollment_started",
    "user_role_updated",
    "user_access_status_updated",
    "reader_greenhouse_access_updated",
    "greenhouse_created",
    "greenhouse_deleted",
}


def _normalize_metadata(metadata: dict | None) -> dict:
    value = metadata or {}
    return {key: entry for key, entry in value.items() if entry is not None}


def log_security_event(
    action: str,
    user_id: str | None = None,
    metadata: dict | None = None,
    ip_address: str | None = None,
) -> None:
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


def get_security_logs(
    limit: int = 100,
    user_id: str | None = None,
    allowed_actions: set[str] | None = None,
) -> list[dict]:
    safe_limit = max(1, min(int(limit), 2000))

    with get_session() as db:
        q = db.query(SecurityLog).order_by(SecurityLog.created_at.desc())
        if user_id:
            q = q.filter(SecurityLog.user_id == user_id)
        if allowed_actions:
            q = q.filter(SecurityLog.action.in_(list(allowed_actions)))

        rows = q.limit(safe_limit).all()
        base_logs = [row.to_dict() for row in rows]

        # enriquece os logs com e-mail e nome da estufa para exibir no painel
        user_ids: set[str] = set()
        greenhouse_ids: set[str] = set()
        greenhouse_id_keys = {"estufaId", "greenhouseId"}
        user_id_keys = {
            "userId",
            "targetUserId",
            "actorId",
            "organizationOwnerId",
            "deletedUserId",
            "dataReassignedToUserId",
        }

        for entry in base_logs:
            if entry.get("userId"):
                user_ids.add(str(entry["userId"]))

            metadata = entry.get("metadata") or {}
            for key, value in metadata.items():
                if isinstance(value, str) and key in user_id_keys:
                    user_ids.add(value)
                if isinstance(value, str) and key in greenhouse_id_keys:
                    greenhouse_ids.add(value)
                if key == "allowedGreenhouseIds" and isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            greenhouse_ids.add(item)

        email_by_user_id: dict[str, str] = {}
        if user_ids:
            user_rows = db.query(User.id, User.email).filter(User.id.in_(list(user_ids))).all()
            email_by_user_id = {row[0]: row[1] for row in user_rows}

        greenhouse_name_by_id: dict[str, str] = {}
        if greenhouse_ids:
            greenhouse_rows = db.query(Estufa.id, Estufa.nome).filter(Estufa.id.in_(list(greenhouse_ids))).all()
            greenhouse_name_by_id = {row[0]: row[1] for row in greenhouse_rows}

        enriched_logs: list[dict] = []
        for entry in base_logs:
            metadata = dict(entry.get("metadata") or {})
            resolved: dict = {}

            executor_id = entry.get("userId")
            if executor_id:
                resolved["executorEmail"] = email_by_user_id.get(str(executor_id))

            for key in user_id_keys:
                value = metadata.get(key)
                if isinstance(value, str):
                    email = email_by_user_id.get(value)
                    if email:
                        resolved[f"{key}Email"] = email

            estufa_id = metadata.get("estufaId") or metadata.get("greenhouseId")
            if isinstance(estufa_id, str):
                estufa_nome = greenhouse_name_by_id.get(estufa_id)
                if estufa_nome:
                    resolved["estufaNomeResolvida"] = estufa_nome

            allowed_ids = metadata.get("allowedGreenhouseIds")
            if isinstance(allowed_ids, list):
                resolved["allowedGreenhouses"] = [
                    {"id": gid, "nome": greenhouse_name_by_id.get(gid)}
                    for gid in allowed_ids
                    if isinstance(gid, str)
                ]

            enriched_logs.append(
                {
                    **entry,
                    "executorEmail": email_by_user_id.get(str(executor_id)) if executor_id else None,
                    "metadata": metadata,
                    "metadataResolved": resolved,
                }
            )

        return enriched_logs
