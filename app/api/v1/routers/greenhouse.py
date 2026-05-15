from typing import Any
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config.flower_profiles import flower_profiles
from app.core.dependencies import get_current_user, get_db
from app.schemas.estufa import CriarEstufa, AtualizarEstufa, EstufaResposta
from app.services.email_service import send_greenhouse_alert_email
from app.services.security_logger import log_security_event
from app.services import address_service
from app.services import greenhouse_service as estufa_service

router = APIRouter(prefix="/api/estufas", tags=["Estufas"])


class UpdateAlertsPayload(BaseModel):
    alertsEnabled: bool = True


class UpdateResponsiblesPayload(BaseModel):
    responsibleUserIds: list[str] = []


class EvaluateMetricsPayload(BaseModel):
    metrics: dict[str, float] = {}
    metricSources: dict[str, str] = {}
    missingMetrics: list[str] = []
    partialEvaluation: bool = False
    notify: bool = False
    forceNotify: bool = False


class UpdateAlertThresholdsPayload(BaseModel):
    # Cada campo é dict {min, max} opcional. null = sem limiar configurado para esse parâmetro.
    temperatura: dict | None = None
    umidade: dict | None = None
    umidade_solo: dict | None = None
    luminosidade: dict | None = None


def _to_range(metric: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(metric, dict):
        return None
    source = metric.get("ideal") if isinstance(metric.get("ideal"), dict) else metric
    min_value = source.get("min")
    max_value = source.get("max")
    if min_value is None or max_value is None:
        return None
    return {"min": float(min_value), "max": float(max_value)}


def _evaluate_range(value: float | None, expected: dict[str, float] | None) -> dict[str, Any]:
    if expected is None:
        return {
            "ok": True,
            "value": value,
            "expected": expected,
            "direction": "not-configured",
            "evaluated": False,
            "delta": None,
        }

    if value is None:
        return {
            "ok": True,
            "value": value,
            "expected": expected,
            "direction": "unavailable",
            "evaluated": False,
            "delta": None,
        }

    if value < expected["min"]:
        return {
            "ok": False,
            "value": value,
            "expected": expected,
            "direction": "low",
            "evaluated": True,
            "delta": round(value - expected["min"], 2),
        }

    if value > expected["max"]:
        return {
            "ok": False,
            "value": value,
            "expected": expected,
            "direction": "high",
            "evaluated": True,
            "delta": round(value - expected["max"], 2),
        }

    return {
        "ok": True,
        "value": value,
        "expected": expected,
        "direction": "in-range",
        "evaluated": True,
        "delta": 0,
    }


def _iso_to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


@router.get("/recomendacoes")
async def listar_recomendacoes() -> dict[str, list[dict[str, Any]]]:
    return {"profiles": flower_profiles}

@router.get("/", response_model=list[EstufaResposta])
async def listar_estufas(
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return estufa_service.listar_estufas(db, user)


@router.get("/cep/{cep}")
async def consultar_cep(cep: str):
    try:
        endereco = address_service.resolve_cep_location(cep)
        return {
            "cep": endereco.get("cep"),
            "cidade": endereco.get("cidade"),
            "estado": endereco.get("estado"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

@router.post("/", response_model=EstufaResposta, status_code=status.HTTP_201_CREATED)
async def criar_estufa(
    payload: CriarEstufa,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        created = estufa_service.criar_estufa(db, user, payload)
        log_security_event(
            "greenhouse_created",
            user_id=user.get("id"),
            metadata={
                "estufaId": created.get("id"),
                "estufaNome": created.get("nome"),
                "role": user.get("role"),
            },
            ip_address=request.client.host if request.client else None,
        )
        return created
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

@router.get("/{estufa_id}", response_model=EstufaResposta)
async def buscar_estufa(
    estufa_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        estufa = estufa_service.buscar_estufa(db, estufa_id, user)
        log_security_event(
            "greenhouse_accessed",
            user_id=user.get("id"),
            metadata={
                "estufaId": estufa_id,
                "estufaNome": estufa.get("nome"),
                "role": user.get("role"),
            },
            ip_address=request.client.host if request.client else None,
        )
        return estufa
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

@router.put("/{estufa_id}", response_model=EstufaResposta)
async def atualizar_estufa(
    estufa_id: str,
    payload: AtualizarEstufa,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        updated = estufa_service.atualizar_estufa(db, estufa_id, user, payload)
        log_security_event(
            "greenhouse_updated",
            user_id=user.get("id"),
            metadata={
                "estufaId": estufa_id,
                "estufaNome": updated.get("nome"),
                "role": user.get("role"),
            },
            ip_address=request.client.host if request.client else None,
        )
        return updated
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

@router.delete("/{estufa_id}", status_code=status.HTTP_200_OK)
async def deletar_estufa(
    estufa_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = estufa_service.deletar_estufa(db, estufa_id, user)
        log_security_event(
            "greenhouse_deleted",
            user_id=user.get("id"),
            metadata={
                "estufaId": estufa_id,
                "role": user.get("role"),
            },
            ip_address=request.client.host if request.client else None,
        )
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/responsaveis/membros")
async def listar_membros_responsaveis(
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"members": estufa_service.list_available_responsibles(db, user)}


@router.patch("/{estufa_id}/team", response_model=EstufaResposta)
async def atualizar_equipe_responsavel(
    estufa_id: str,
    payload: UpdateResponsiblesPayload,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        updated = estufa_service.update_estufa_responsibles(db, estufa_id, user, payload.responsibleUserIds)
        log_security_event(
            "greenhouse_team_updated",
            user_id=user.get("id"),
            metadata={
                "estufaId": estufa_id,
                "responsaveis": updated.get("responsible_user_ids", []),
            },
            ip_address=request.client.host if request.client else None,
        )
        return updated
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.patch("/{estufa_id}/alerts", response_model=EstufaResposta)
async def atualizar_alertas_estufa(
    estufa_id: str,
    payload: UpdateAlertsPayload,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        updated = estufa_service.update_estufa_alerts(db, estufa_id, user, payload.alertsEnabled)
        log_security_event(
            "greenhouse_alerts_updated",
            user_id=user.get("id"),
            metadata={
                "estufaId": estufa_id,
                "alertsEnabled": bool(payload.alertsEnabled),
            },
            ip_address=request.client.host if request.client else None,
        )
        return updated
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/{estufa_id}/evaluate")
async def avaliar_metricas_estufa(
    estufa_id: str,
    payload: EvaluateMetricsPayload,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # notifica só os responsáveis delegados, não todos os admins
    try:
        estufa = estufa_service.buscar_estufa(db, estufa_id, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    preset = estufa.get("preset")
    if not preset:
        return {
            "status": "pending",
            "alerts": [],
            "metricsEvaluation": {},
            "notified": False,
            "greenhouse": estufa,
        }

    expected = {
        "temperature": _to_range(preset.get("temperatura")),
        "humidity": _to_range(preset.get("umidade")),
        "soilMoisture": _to_range(preset.get("umidade_solo")),
        "luminosity": _to_range(preset.get("luminosidade")),
    }

    metric_values = {
        "temperature": payload.metrics.get("temperature"),
        "humidity": payload.metrics.get("humidity"),
        "soilMoisture": payload.metrics.get("soilMoisture"),
        "luminosity": payload.metrics.get("luminosity"),
    }

    allowed_sources = {"internal", "external"}

    def _resolve_source(metric_name: str) -> str:
        provided = (payload.metricSources.get(metric_name) or "").strip().lower()
        if provided in allowed_sources:
            return provided
        if metric_values.get(metric_name) is None:
            return "unavailable"
        return "internal"

    metric_sources = {
        "temperature": _resolve_source("temperature"),
        "humidity": _resolve_source("humidity"),
        "soilMoisture": _resolve_source("soilMoisture"),
        "luminosity": _resolve_source("luminosity"),
    }

    metrics_evaluation = {
        "temperature": _evaluate_range(metric_values["temperature"], expected["temperature"]),
        "humidity": _evaluate_range(metric_values["humidity"], expected["humidity"]),
        "soilMoisture": _evaluate_range(metric_values["soilMoisture"], expected["soilMoisture"]),
        "luminosity": _evaluate_range(metric_values["luminosity"], expected["luminosity"]),
    }

    metrics_coverage = {
        "temperature": bool(expected["temperature"] is not None and metric_values["temperature"] is not None),
        "humidity": bool(expected["humidity"] is not None and metric_values["humidity"] is not None),
        "soilMoisture": bool(expected["soilMoisture"] is not None and metric_values["soilMoisture"] is not None),
        "luminosity": bool(expected["luminosity"] is not None and metric_values["luminosity"] is not None),
    }
    missing_metrics = [
        metric_name
        for metric_name, covered in metrics_coverage.items()
        if not covered and expected.get(metric_name) is not None
    ]
    # parcial quando o front sinaliza ou quando algum parâmetro esperado não veio
    is_partial_evaluation = bool(payload.partialEvaluation or missing_metrics)

    alerts: list[str] = []
    if metrics_evaluation["temperature"]["evaluated"] and not metrics_evaluation["temperature"]["ok"] and expected["temperature"]:
        alerts.append(
            f"Temperatura fora do ideal ({expected['temperature']['min']}°C - {expected['temperature']['max']}°C)."
        )
    if metrics_evaluation["humidity"]["evaluated"] and not metrics_evaluation["humidity"]["ok"] and expected["humidity"]:
        alerts.append(
            f"Umidade relativa fora do ideal ({expected['humidity']['min']}% - {expected['humidity']['max']}%)."
        )
    if metrics_evaluation["soilMoisture"]["evaluated"] and not metrics_evaluation["soilMoisture"]["ok"] and expected["soilMoisture"]:
        alerts.append(
            f"Umidade do solo fora do ideal ({expected['soilMoisture']['min']}% - {expected['soilMoisture']['max']}%)."
        )
    if metrics_evaluation["luminosity"]["evaluated"] and not metrics_evaluation["luminosity"]["ok"] and expected["luminosity"]:
        alerts.append(
            f"Luminosidade fora do ideal ({expected['luminosity']['min']} - {expected['luminosity']['max']} lux)."
        )

    should_notify = bool(payload.notify) and len(alerts) > 0
    throttled = False
    notified = False

    if should_notify:
        now = datetime.now(timezone.utc)
        cooldown_limit = now - timedelta(minutes=15)
        last_alert_at = _iso_to_datetime(estufa.get("last_alert_at"))
        is_cooldown_active = bool(last_alert_at and last_alert_at > cooldown_limit)
        if is_cooldown_active and not payload.forceNotify:
            throttled = True
        else:
            recipients = [
                watcher.get("email")
                for watcher in (estufa.get("watchers_details") or [])
                if watcher.get("email")
            ]
            recipients = [email for email in recipients if email]
            if recipients:
                send_greenhouse_alert_email(
                    recipients=recipients,
                    greenhouse_name=estufa.get("nome") or "Estufa",
                    profile={
                        "name": preset.get("nome_cultura") or "Perfil",
                    },
                    metrics=metric_values,
                    metrics_evaluation=metrics_evaluation,
                    metric_sources=metric_sources,
                    partial_evaluation=is_partial_evaluation,
                    alerts=alerts,
                )
                estufa_service.mark_last_alert_sent(db, estufa_id)
                estufa = estufa_service.buscar_estufa(db, estufa_id, user)
                notified = True

    log_security_event(
        "greenhouse_metrics_evaluated",
        user_id=user.get("id"),
        metadata={
            "estufaId": estufa_id,
            "status": "alert" if alerts else "ok",
            "notified": notified,
            "throttled": throttled,
            "partialEvaluation": is_partial_evaluation,
            "missingMetrics": missing_metrics,
            "responsibleCount": len(estufa.get("responsible_user_ids") or []),
        },
        ip_address=request.client.host if request.client else None,
    )

    return {
        "status": "alert" if alerts else "ok",
        "alerts": alerts,
        "metricsEvaluation": metrics_evaluation,
        "notified": notified,
        "throttled": throttled,
        "partialEvaluation": is_partial_evaluation,
        "missingMetrics": missing_metrics,
        "metricSources": metric_sources,
        "responsibleCount": len(estufa.get("responsible_user_ids") or []),
        "greenhouse": estufa,
    }


@router.patch("/{estufa_id}/alert-thresholds")
async def atualizar_alert_thresholds(
    estufa_id: str,
    payload: UpdateAlertThresholdsPayload,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Salva limiares de alerta personalizados para a estufa.
    if (user.get("role") or "").strip() == "Reader":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Perfil Leitor possui acesso somente de consulta.")

    estufa = db.query(estufa_service._Estufa_model()).filter_by(id=estufa_id).first() if False else None

    # busca pelo ORM direto
    from app.models.estufa import Estufa as EstufaModel
    estufa = db.query(EstufaModel).filter(EstufaModel.id == estufa_id).first()
    if not estufa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Estufa não encontrada.")
    if not estufa_service._can_access_greenhouse_ids(estufa.id, estufa.user_id, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão para editar esta estufa.")

    thresholds = {}
    if payload.temperatura is not None:
        thresholds["temperatura"] = payload.temperatura
    if payload.umidade is not None:
        thresholds["umidade"] = payload.umidade
    if payload.substrato is not None:
        thresholds["substrato"] = payload.substrato

    estufa.alert_thresholds = thresholds if thresholds else None
    db.commit()

    atualizada = estufa_service.buscar_estufa(db, estufa_id, user)
    return atualizada
