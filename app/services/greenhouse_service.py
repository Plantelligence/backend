"""Gerenciamento de estufas: cadastro, configuracao, avaliacao de metricas e envio de alertas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.config.flower_profiles import find_flower_profile, flower_profiles
from app.db.postgres.session import get_session
from app.models.greenhouse import Greenhouse
from app.services.auth_service import get_user_by_id
from app.services.email_service import send_greenhouse_alert_email
from app.services.security_logger import log_security_event

ALERT_COOLDOWN_MS = 15 * 60 * 1000
MAX_WATCHERS = 12


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def ensure_watcher_array(watchers: list[str] | None) -> list[str]:
    if not isinstance(watchers, list):
        return []
    values = [str(v).strip() for v in watchers if str(v).strip()]
    return sorted(set(values))


def map_greenhouse_record(record: Greenhouse) -> dict:
    return record.to_dict()


def get_user_snapshot(user_id: str | None) -> dict | None:
    if not user_id:
        return None
    user = get_user_by_id(user_id)
    if not user:
        return None
    return {
        "id": user["id"],
        "email": user["email"],
        "fullName": user.get("fullName"),
        "role": user.get("role", "User"),
    }


def enrich_with_profile_and_watchers(record: dict) -> dict:
    profile = find_flower_profile(record.get("flowerProfileId")) if record.get("flowerProfileId") else None
    details = [item for item in (get_user_snapshot(wid) for wid in record.get("watchers", [])) if item]
    return {**record, "profile": profile, "watchersDetails": details}


def get_greenhouse_record_by_id(greenhouse_id: str) -> dict | None:
    with get_session() as db:
        g = db.query(Greenhouse).filter(Greenhouse.id == greenhouse_id).first()
        return g.to_dict() if g else None


def resolve_owner_greenhouses(owner_id: str) -> list[dict]:
    """Busca todas as estufas do usuario no banco e enriquece com perfil e equipe."""
    with get_session() as db:
        greenhouses = db.query(Greenhouse).filter(Greenhouse.owner_id == owner_id).order_by(Greenhouse.created_at).all()
        records = [g.to_dict() for g in greenhouses]

    return [enrich_with_profile_and_watchers(r) for r in records]


def assert_ownership(record: dict | None, owner_id: str) -> None:
    """Lanca excecao se a estufa nao existir ou nao pertencer ao usuario informado."""
    if not record:
        raise FileNotFoundError("Estufa nao encontrada.")
    if record.get("ownerId") != owner_id:
        raise PermissionError("Voce nao tem permissao para alterar esta estufa.")


def normalize_metric(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def evaluate_single_metric(value: Any, expected: dict) -> dict:
    normalized_value = normalize_metric(value)
    min_value = float(expected["min"])
    max_value = float(expected["max"])

    if normalized_value is None:
        return {"ok": False, "value": None, "deviation": None, "expected": {"min": min_value, "max": max_value}}

    if normalized_value < min_value:
        return {"ok": False, "value": normalized_value, "deviation": min_value - normalized_value, "expected": {"min": min_value, "max": max_value}, "direction": "low"}

    if normalized_value > max_value:
        return {"ok": False, "value": normalized_value, "deviation": normalized_value - max_value, "expected": {"min": min_value, "max": max_value}, "direction": "high"}

    return {"ok": True, "value": normalized_value, "deviation": 0, "expected": {"min": min_value, "max": max_value}, "direction": "in-range"}


def build_alert_summary(profile: dict, metrics_evaluation: dict, metrics: dict | None = None) -> list[str]:
    metrics = metrics or {}
    alerts: list[str] = []

    def fmt(metric_key: str) -> str:
        entry = metrics_evaluation.get(metric_key) or {}
        value = entry.get("value")
        if value is None:
            fallback = normalize_metric(metrics.get(metric_key))
            return "n/d" if fallback is None else f"{fallback:.1f}".rstrip("0").rstrip(".")
        return f"{float(value):.1f}".rstrip("0").rstrip(".")

    if not metrics_evaluation["temperature"]["ok"]:
        e = profile["temperature"]
        alerts.append(f"Temperatura em {fmt('temperature')}°C (ideal {e['min']}°C - {e['max']}°C).")
    if not metrics_evaluation["humidity"]["ok"]:
        e = profile["humidity"]
        alerts.append(f"Umidade relativa em {fmt('humidity')}% (ideal {e['min']}% - {e['max']}%).")
    if not metrics_evaluation["soilMoisture"]["ok"]:
        e = profile["soilMoisture"]
        alerts.append(f"Umidade do substrato em {fmt('soilMoisture')}% (ideal {e['min']}% - {e['max']}%).")

    return alerts


def list_flower_profiles() -> list[dict]:
    return flower_profiles


def list_greenhouses(owner_id: str) -> list[dict]:
    return resolve_owner_greenhouses(owner_id)


def list_greenhouses_for_admin(owner_id: str) -> list[dict]:
    return resolve_owner_greenhouses(owner_id)


def create_greenhouse(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    if len(name) < 3 or len(name) > 80:
        raise ValueError("Nome da estufa deve ter entre 3 e 80 caracteres.")

    profile_id = payload.get("flowerProfileId")
    profile = find_flower_profile(profile_id) if profile_id else None
    if profile_id and not profile:
        raise ValueError("Perfil de cultivo de cogumelo invalido.")

    greenhouse_id = str(uuid4())

    with get_session() as db:
        db.add(Greenhouse(
            id=greenhouse_id,
            owner_id=payload["ownerId"],
            name=name,
            flower_profile_id=profile.get("id") if profile else None,
            watchers=[],
            alerts_enabled=True,
            last_alert_at=None,
        ))

    log_security_event("greenhouse_created", user_id=payload["ownerId"], metadata={"greenhouseId": greenhouse_id, "flowerProfileId": profile.get("id") if profile else None})
    return enrich_with_profile_and_watchers(get_greenhouse_record_by_id(greenhouse_id) or {})


def get_greenhouse_for_owner(payload: dict) -> dict:
    record = get_greenhouse_record_by_id(payload["greenhouseId"])
    assert_ownership(record, payload["ownerId"])
    return enrich_with_profile_and_watchers(record)


def get_greenhouse_for_admin(greenhouse_id: str) -> dict:
    record = get_greenhouse_record_by_id(greenhouse_id)
    if not record:
        raise FileNotFoundError("Estufa nao encontrada.")
    return enrich_with_profile_and_watchers(record)


def update_greenhouse_basics(payload: dict) -> dict:
    record = get_greenhouse_record_by_id(payload["greenhouseId"])
    assert_ownership(record, payload["ownerId"])

    name = (payload.get("name") or "").strip()
    if len(name) < 3 or len(name) > 80:
        raise ValueError("Nome da estufa deve ter entre 3 e 80 caracteres.")

    profile = find_flower_profile(payload.get("flowerProfileId"))
    if not profile:
        raise ValueError("Perfil de cultivo de cogumelo invalido.")

    with get_session() as db:
        g = db.query(Greenhouse).filter(Greenhouse.id == payload["greenhouseId"]).first()
        if g:
            g.name = name
            g.flower_profile_id = profile["id"]

    log_security_event("greenhouse_config_updated", user_id=payload["ownerId"], metadata={"greenhouseId": payload["greenhouseId"], "flowerProfileId": profile["id"], "name": name})
    return get_greenhouse_for_owner(payload)


def update_alert_settings(payload: dict) -> dict:
    record = get_greenhouse_record_by_id(payload["greenhouseId"])
    assert_ownership(record, payload["ownerId"])

    enabled = bool(payload.get("alertsEnabled"))
    with get_session() as db:
        g = db.query(Greenhouse).filter(Greenhouse.id == payload["greenhouseId"]).first()
        if g:
            g.alerts_enabled = enabled

    log_security_event("greenhouse_alerts_setting_updated", user_id=payload["ownerId"], metadata={"greenhouseId": payload["greenhouseId"], "alertsEnabled": enabled})
    return get_greenhouse_for_owner(payload)


def delete_greenhouse(payload: dict) -> dict:
    record = get_greenhouse_record_by_id(payload["greenhouseId"])
    assert_ownership(record, payload["ownerId"])

    with get_session() as db:
        db.query(Greenhouse).filter(Greenhouse.id == payload["greenhouseId"]).delete(synchronize_session=False)

    log_security_event("greenhouse_deleted", user_id=payload["ownerId"], metadata={"greenhouseId": payload["greenhouseId"]})
    return {
        "deletedId": payload["greenhouseId"],
        "greenhouses": resolve_owner_greenhouses(payload["ownerId"]),
    }


def update_greenhouse_team(payload: dict) -> dict:
    actor = get_user_by_id(payload["actorUserId"])
    if not actor or actor.get("role") != "Admin":
        raise PermissionError("Apenas administradores podem ajustar a equipe de alertas.")

    record = get_greenhouse_record_by_id(payload["greenhouseId"])
    if not record:
        raise FileNotFoundError("Estufa nao encontrada.")

    watcher_ids = ensure_watcher_array(payload.get("watcherIds", []))
    if len(watcher_ids) > MAX_WATCHERS:
        raise ValueError("Limite maximo de 12 integrantes por equipe.")

    snapshots = [get_user_snapshot(wid) for wid in watcher_ids]
    if any(s is None for s in snapshots):
        raise FileNotFoundError("Integrantes invalidos informados para a equipe.")

    with get_session() as db:
        g = db.query(Greenhouse).filter(Greenhouse.id == payload["greenhouseId"]).first()
        if g:
            g.watchers = watcher_ids

    log_security_event("greenhouse_team_updated", user_id=record["ownerId"], metadata={"greenhouseId": payload["greenhouseId"], "actorId": payload["actorUserId"], "watchers": watcher_ids})
    return get_greenhouse_for_admin(payload["greenhouseId"])


def evaluate_and_handle_greenhouse_metrics(payload: dict) -> dict:
    record = get_greenhouse_record_by_id(payload["greenhouseId"])
    assert_ownership(record, payload["ownerId"])

    if not record.get("flowerProfileId"):
        raise ValueError("Defina o tipo de cultivo para habilitar a monitoracao.")

    profile = find_flower_profile(record["flowerProfileId"])
    if not profile:
        raise FileNotFoundError("Perfil de cultivo nao esta disponivel.")

    metrics = payload.get("metrics") or {}
    metrics_evaluation = {
        "temperature": evaluate_single_metric(metrics.get("temperature"), profile["temperature"]),
        "humidity": evaluate_single_metric(metrics.get("humidity"), profile["humidity"]),
        "soilMoisture": evaluate_single_metric(metrics.get("soilMoisture"), profile["soilMoisture"]),
    }

    alerts = build_alert_summary(profile, metrics_evaluation, metrics)
    status = "ok" if not alerts else "alert"
    notified = False
    throttled = False

    if payload.get("notify") and status == "alert" and record.get("alertsEnabled", True):
        owner = get_user_snapshot(payload["ownerId"])
        watcher_details = [get_user_snapshot(wid) for wid in record.get("watchers", [])]
        recipients = [e["email"] for e in [owner, *watcher_details] if e and e.get("email")]
        unique_emails = sorted(set(recipients))

        if unique_emails:
            now = datetime.now(UTC)
            last_alert_at = record.get("lastAlertAt")
            force_notify = bool(payload.get("forceNotify"))

            if not force_notify and last_alert_at:
                previous = datetime.fromisoformat(last_alert_at)
                if (now - previous).total_seconds() * 1000 < ALERT_COOLDOWN_MS:
                    throttled = True

            if not throttled:
                send_greenhouse_alert_email(
                    recipients=unique_emails,
                    greenhouse_name=record["name"],
                    profile=profile,
                    metrics=metrics,
                    metrics_evaluation=metrics_evaluation,
                    alerts=alerts,
                )
                notified = True
                with get_session() as db:
                    g = db.query(Greenhouse).filter(Greenhouse.id == payload["greenhouseId"]).first()
                    if g:
                        g.last_alert_at = now.isoformat()

                log_security_event("greenhouse_alert_email_sent", user_id=payload["ownerId"], metadata={"greenhouseId": payload["greenhouseId"], "profileId": profile["id"], "alerts": alerts, "forced": force_notify})

    refreshed = get_greenhouse_for_owner({"greenhouseId": payload["greenhouseId"], "ownerId": payload["ownerId"]})

    return {
        "greenhouse": refreshed,
        "profile": refreshed.get("profile"),
        "metricsEvaluation": metrics_evaluation,
        "alerts": alerts,
        "status": status,
        "notified": notified,
        "throttled": throttled,
        "alertsEnabled": refreshed.get("alertsEnabled"),
    }


# --- Sensores, atuadores e parametros gerais ---
# Cada uma dessas funcoes le o registro atual, valida ownership e
# persiste o novo valor em JSON. O esquema de cada item e livre — o
# frontend define a forma dos objetos sensor/atuador conforme precisar.

def get_greenhouse_config_extended(payload: dict) -> dict:
    """Retorna sensores, atuadores e parametros gerais da estufa."""
    record = get_greenhouse_record_by_id(payload["greenhouseId"])
    assert_ownership(record, payload["ownerId"])
    return {
        "sensors": record.get("sensors") or [],
        "actuators": record.get("actuators") or [],
        "parameters": record.get("parameters") or {},
    }


def update_greenhouse_sensors(payload: dict) -> dict:
    """Substitui a lista de sensores da estufa."""
    record = get_greenhouse_record_by_id(payload["greenhouseId"])
    assert_ownership(record, payload["ownerId"])

    sensors = payload.get("sensors") if isinstance(payload.get("sensors"), list) else []
    with get_session() as db:
        g = db.query(Greenhouse).filter(Greenhouse.id == payload["greenhouseId"]).first()
        if g:
            g.sensors = sensors

    log_security_event("greenhouse_sensors_updated", user_id=payload["ownerId"], metadata={"greenhouseId": payload["greenhouseId"], "count": len(sensors)})
    return get_greenhouse_config_extended(payload)


def update_greenhouse_actuators(payload: dict) -> dict:
    """Substitui a lista de atuadores da estufa."""
    record = get_greenhouse_record_by_id(payload["greenhouseId"])
    assert_ownership(record, payload["ownerId"])

    actuators = payload.get("actuators") if isinstance(payload.get("actuators"), list) else []
    with get_session() as db:
        g = db.query(Greenhouse).filter(Greenhouse.id == payload["greenhouseId"]).first()
        if g:
            g.actuators = actuators

    log_security_event("greenhouse_actuators_updated", user_id=payload["ownerId"], metadata={"greenhouseId": payload["greenhouseId"], "count": len(actuators)})
    return get_greenhouse_config_extended(payload)


def update_greenhouse_parameters(payload: dict) -> dict:
    """Atualiza os parametros gerais da estufa (merge com os existentes)."""
    record = get_greenhouse_record_by_id(payload["greenhouseId"])
    assert_ownership(record, payload["ownerId"])

    existing = record.get("parameters") or {}
    incoming = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
    merged = {**existing, **incoming}

    with get_session() as db:
        g = db.query(Greenhouse).filter(Greenhouse.id == payload["greenhouseId"]).first()
        if g:
            g.parameters = merged

    log_security_event("greenhouse_parameters_updated", user_id=payload["ownerId"], metadata={"greenhouseId": payload["greenhouseId"]})
    return get_greenhouse_config_extended(payload)
