"""Rotas para cadastro e gerenciamento de estufas, avaliacao de metricas e alertas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user
from app.services.greenhouse_service import (
    create_greenhouse,
    delete_greenhouse,
    evaluate_and_handle_greenhouse_metrics,
    get_greenhouse_config_extended,
    get_greenhouse_for_owner,
    list_flower_profiles,
    list_greenhouses,
    update_alert_settings,
    update_greenhouse_actuators,
    update_greenhouse_basics,
    update_greenhouse_parameters,
    update_greenhouse_sensors,
)

router = APIRouter(prefix="/api/greenhouse", tags=["greenhouse"])


class CreateGreenhouseRequest(BaseModel):
    name: str
    flowerProfileId: str | None = None


class UpdateGreenhouseRequest(BaseModel):
    name: str
    flowerProfileId: str


class UpdateAlertSettingsRequest(BaseModel):
    alertsEnabled: bool


class EvaluateMetricsRequest(BaseModel):
    metrics: dict = Field(default_factory=dict)
    notify: bool = False
    forceNotify: bool = False


class UpdateSensorsRequest(BaseModel):
    sensors: list = Field(default_factory=list)


class UpdateActuatorsRequest(BaseModel):
    actuators: list = Field(default_factory=list)


class UpdateParametersRequest(BaseModel):
    parameters: dict = Field(default_factory=dict)


@router.get("/recommendations")
async def recommendations(_: dict = Depends(get_current_user)) -> dict:
    """Retorna perfis de cultivo com faixas ideais."""

    return {"profiles": list_flower_profiles()}


@router.get("/")
async def list_owner_greenhouses(user: dict = Depends(get_current_user)) -> dict:
    """Lista estufas do usuario autenticado."""

    try:
        return {"greenhouses": list_greenhouses(user["id"])}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_owner_greenhouse(payload: CreateGreenhouseRequest, user: dict = Depends(get_current_user)) -> dict:
    """Cria estufa para usuario autenticado."""

    try:
        greenhouse = create_greenhouse(
            {
                "ownerId": user["id"],
                "name": payload.name,
                "flowerProfileId": payload.flowerProfileId,
            }
        )
        greenhouses = list_greenhouses(user["id"])
        return {"greenhouse": greenhouse, "greenhouses": greenhouses}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{greenhouse_id}")
async def owner_greenhouse(greenhouse_id: str, user: dict = Depends(get_current_user)) -> dict:
    """Retorna estufa especifica do owner."""

    try:
        greenhouse = get_greenhouse_for_owner({"greenhouseId": greenhouse_id, "ownerId": user["id"]})
        return {"greenhouse": greenhouse}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.put("/{greenhouse_id}")
async def update_owner_greenhouse(greenhouse_id: str, payload: UpdateGreenhouseRequest, user: dict = Depends(get_current_user)) -> dict:
    """Atualiza nome e perfil de cultivo da estufa."""

    try:
        greenhouse = update_greenhouse_basics(
            {
                "greenhouseId": greenhouse_id,
                "ownerId": user["id"],
                "name": payload.name,
                "flowerProfileId": payload.flowerProfileId,
            }
        )
        return {"greenhouse": greenhouse}
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{greenhouse_id}")
async def delete_owner_greenhouse(greenhouse_id: str, user: dict = Depends(get_current_user)) -> dict:
    """Exclui estufa do usuario autenticado."""

    try:
        return delete_greenhouse({"greenhouseId": greenhouse_id, "ownerId": user["id"]})
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{greenhouse_id}/alerts")
async def patch_alerts(greenhouse_id: str, payload: UpdateAlertSettingsRequest, user: dict = Depends(get_current_user)) -> dict:
    """Atualiza flag de envio de alertas automaticos da estufa."""

    try:
        greenhouse = update_alert_settings(
            {
                "greenhouseId": greenhouse_id,
                "ownerId": user["id"],
                "alertsEnabled": payload.alertsEnabled,
            }
        )
        return {"greenhouse": greenhouse}
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{greenhouse_id}/evaluate")
async def evaluate_metrics(greenhouse_id: str, payload: EvaluateMetricsRequest, user: dict = Depends(get_current_user)) -> dict:
    """Avalia metricas, compara com perfil e notifica por e-mail quando preciso."""

    try:
        return evaluate_and_handle_greenhouse_metrics(
            {
                "greenhouseId": greenhouse_id,
                "ownerId": user["id"],
                "metrics": payload.metrics,
                "notify": payload.notify,
                "forceNotify": payload.forceNotify,
            }
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{greenhouse_id}/config")
async def get_config(greenhouse_id: str, user: dict = Depends(get_current_user)) -> dict:
    """Retorna sensores, atuadores e parametros gerais da estufa."""

    try:
        return get_greenhouse_config_extended({"greenhouseId": greenhouse_id, "ownerId": user["id"]})
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.put("/{greenhouse_id}/sensors")
async def update_sensors(greenhouse_id: str, payload: UpdateSensorsRequest, user: dict = Depends(get_current_user)) -> dict:
    """Atualiza lista de sensores da estufa."""

    try:
        return update_greenhouse_sensors({"greenhouseId": greenhouse_id, "ownerId": user["id"], "sensors": payload.sensors})
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/{greenhouse_id}/actuators")
async def update_actuators(greenhouse_id: str, payload: UpdateActuatorsRequest, user: dict = Depends(get_current_user)) -> dict:
    """Atualiza lista de atuadores da estufa."""

    try:
        return update_greenhouse_actuators({"greenhouseId": greenhouse_id, "ownerId": user["id"], "actuators": payload.actuators})
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{greenhouse_id}/parameters")
async def update_parameters(greenhouse_id: str, payload: UpdateParametersRequest, user: dict = Depends(get_current_user)) -> dict:
    """Atualiza (merge) parametros gerais da estufa."""

    try:
        return update_greenhouse_parameters({"greenhouseId": greenhouse_id, "ownerId": user["id"], "parameters": payload.parameters})
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
