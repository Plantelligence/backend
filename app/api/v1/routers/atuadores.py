"""
Rotas para controle remoto de atuadores via Azure IoT Hub.

Endpoints disponiveis:
  POST   /api/estufas/{estufa_id}/atuadores/{dispositivo_id}/comando       — envia comando generico
  POST   /api/estufas/{estufa_id}/atuadores/{dispositivo_id}/ligar         — atalho para ligar
  POST   /api/estufas/{estufa_id}/atuadores/{dispositivo_id}/desligar      — atalho para desligar
  POST   /api/estufas/{estufa_id}/atuadores/{dispositivo_id}/ajustar       — atalho para ajustar parametro
  GET    /api/estufas/{estufa_id}/atuadores/{dispositivo_id}/comandos      — historico de comandos
  GET    /api/estufas/{estufa_id}/atuadores/{dispositivo_id}/status        — status do dispositivo (device twin)

Controle de acesso:
  - Reader nao pode enviar comandos (somente consultar historico e status)
  - Admin e Collaborator podem enviar comandos
  - Usuario deve ter acesso a estufa (dono, responsavel ou admin)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.command_history import CommandHistory
from app.models.dispositivo import Dispositivo
from app.models.estufa import Estufa
from app.schemas.comando import (
    ComandoResposta,
    EnviarComandoRequest,
    HistoricoComandoResposta,
)

router = APIRouter(prefix="/api/estufas", tags=["Atuadores"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_estufa_e_dispositivo(
    estufa_id: str,
    dispositivo_id: str,
    user: dict[str, Any],
    db: Session,
) -> tuple[Estufa, Dispositivo]:
    """Carrega estufa e dispositivo, verificando permissao de acesso."""
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

    dispositivo = db.query(Dispositivo).filter(
        Dispositivo.id == dispositivo_id,
        Dispositivo.estufa_id == estufa_id,
    ).first()
    if not dispositivo:
        raise HTTPException(status_code=404, detail="Dispositivo nao encontrado nesta estufa.")

    return estufa, dispositivo


def _assert_can_send_command(user: dict[str, Any]) -> None:
    """Verifica se o usuario pode enviar comandos (Reader nao pode)."""
    if (user.get("role") or "").strip() == "Reader":
        raise HTTPException(
            status_code=403,
            detail="Perfil Leitor nao pode enviar comandos a atuadores.",
        )

    # verifica permissao granular se existir
    perms = user.get("permissions") or {}
    if perms.get("canControlActuators") is False:
        raise HTTPException(
            status_code=403,
            detail="Voce nao tem permissao para controlar atuadores.",
        )


def _assert_is_actuator(dispositivo: Dispositivo) -> None:
    """Verifica se o dispositivo e um atuador (nao sensor)."""
    if not dispositivo.tipo.lower().startswith("atuador"):
        raise HTTPException(
            status_code=400,
            detail=f"Dispositivo '{dispositivo.nome}' nao e um atuador (tipo: {dispositivo.tipo}).",
        )


def _command_to_status_label(cmd_status: str) -> str:
    """Mapeia status do comando para label legivel."""
    labels = {
        "pending": "Enfileirado",
        "sent": "Enviado ao IoT Hub",
        "delivered": "Confirmado pelo dispositivo",
        "failed": "Falha no envio",
        "expired": "Expirado",
    }
    return labels.get(cmd_status, cmd_status)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{estufa_id}/atuadores/{dispositivo_id}/comando", response_model=ComandoResposta)
async def enviar_comando(
    estufa_id: str,
    dispositivo_id: str,
    payload: EnviarComandoRequest,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Envia um comando a um atuador via Azure IoT Hub.

    Tipos de comando:
      - ligar: ativa o atuador
      - desligar: desativa o atuador
      - ajustar: define um valor especifico (ex.: intensidade=70%)
      - custom: comando arbitrario

    Metodos de entrega:
      - cloud_to_device: mensagem enfileirada (assincrono, sem resposta)
      - direct_method: chamada sincrona com resposta do dispositivo
    """
    _assert_can_send_command(user)
    estufa, dispositivo = _get_estufa_e_dispositivo(estufa_id, dispositivo_id, user, db)
    _assert_is_actuator(dispositivo)

    if not dispositivo.iothub_device_id:
        raise HTTPException(
            status_code=400,
            detail="Dispositivo nao possui credenciais IoT Hub. Registre-o no IoT Hub primeiro.",
        )

    if not dispositivo.ativo:
        raise HTTPException(
            status_code=400,
            detail="Dispositivo desativado. Ative-o antes de enviar comandos.",
        )

    # constroi o payload padronizado para o firmware ESP32
    from app.services.iothub_command_service import build_actuator_payload, get_command_service

    command_payload = build_actuator_payload(payload.command_type, payload.payload)

    # registra no historico como pending
    command_record = CommandHistory(
        dispositivo_id=dispositivo_id,
        command_type=payload.command_type,
        payload=command_payload,
        delivery_method=payload.delivery_method,
        status="pending",
        sent_by_user_id=user.get("id"),
        reason=payload.reason,
    )
    db.add(command_record)
    db.commit()
    db.refresh(command_record)

    # envia ao IoT Hub
    try:
        service = get_command_service()

        if payload.delivery_method == "direct_method":
            # chamada sincrona — aguarda resposta do dispositivo
            result = await service.invoke_direct_method(
                device_id=dispositivo.iothub_device_id,
                method_name=payload.command_type,
                payload=command_payload,
                timeout_seconds=payload.timeout_seconds,
            )

            command_record.status = "delivered" if result.get("status") == 200 else "failed"
            command_record.response_payload = result.get("payload")
            if command_record.status == "failed":
                command_record.error_message = f"Dispositivo retornou status {result.get('status')}"

        else:
            # cloud-to-device — fire and forget
            result = await service.send_c2d_message(
                device_id=dispositivo.iothub_device_id,
                payload=command_payload,
            )

            command_record.status = "sent"

        db.commit()
        db.refresh(command_record)

        return ComandoResposta(
            commandId=command_record.id,
            dispositivoId=command_record.dispositivo_id,
            commandType=command_record.command_type,
            deliveryMethod=command_record.delivery_method,
            status=_command_to_status_label(command_record.status),
            errorMessage=command_record.error_message,
            responsePayload=command_record.response_payload,
            createdAt=command_record.created_at.isoformat() if command_record.created_at else None,
        )

    except RuntimeError as exc:
        command_record.status = "failed"
        command_record.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        command_record.status = "failed"
        command_record.error_message = str(exc)
        db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao enviar comando: {exc}",
        ) from exc


@router.post("/{estufa_id}/atuadores/{dispositivo_id}/ligar", response_model=ComandoResposta)
async def ligar_atuador(
    estufa_id: str,
    dispositivo_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Atalho para ligar um atuador.
    Equivalente a enviar comando {command_type: "ligar"} via cloud_to_device.
    """
    _assert_can_send_command(user)
    estufa, dispositivo = _get_estufa_e_dispositivo(estufa_id, dispositivo_id, user, db)
    _assert_is_actuator(dispositivo)

    # reutiliza o endpoint generico
    from app.schemas.comando import EnviarComandoRequest

    payload = EnviarComandoRequest(
        command_type="ligar",
        delivery_method="cloud_to_device",
        reason=f"Ligado via dashboard — {dispositivo.nome}",
    )
    return await enviar_comando(estufa_id, dispositivo_id, payload, user, db)


@router.post("/{estufa_id}/atuadores/{dispositivo_id}/desligar", response_model=ComandoResposta)
async def desligar_atuador(
    estufa_id: str,
    dispositivo_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Atalho para desligar um atuador.
    Equivalente a enviar comando {command_type: "desligar"} via cloud_to_device.
    """
    _assert_can_send_command(user)
    estufa, dispositivo = _get_estufa_e_dispositivo(estufa_id, dispositivo_id, user, db)
    _assert_is_actuator(dispositivo)

    from app.schemas.comando import EnviarComandoRequest

    payload = EnviarComandoRequest(
        command_type="desligar",
        delivery_method="cloud_to_device",
        reason=f"Desligado via dashboard — {dispositivo.nome}",
    )
    return await enviar_comando(estufa_id, dispositivo_id, payload, user, db)


@router.post("/{estufa_id}/atuadores/{dispositivo_id}/ajustar", response_model=ComandoResposta)
async def ajustar_atuador(
    estufa_id: str,
    dispositivo_id: str,
    parameter: str,
    value: float,
    unit: str | None = None,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Atalho para ajustar um parametro do atuador.

    Exemplos:
      parameter=intensidade, value=70, unit=%  → ajusta luminosidade para 70%
      parameter=vazao, value=2.5, unit=L/min   → ajusta irrigacao para 2.5 L/min
      parameter=velocidade, value=80, unit=%    → ajusta ventilacao para 80%
    """
    _assert_can_send_command(user)
    estufa, dispositivo = _get_estufa_e_dispositivo(estufa_id, dispositivo_id, user, db)
    _assert_is_actuator(dispositivo)

    from app.schemas.comando import EnviarComandoRequest

    payload = EnviarComandoRequest(
        command_type="ajustar",
        payload={"parameter": parameter, "value": value, "unit": unit},
        delivery_method="cloud_to_device",
        reason=f"Ajuste {parameter}={value}{unit or ''} via dashboard — {dispositivo.nome}",
    )
    return await enviar_comando(estufa_id, dispositivo_id, payload, user, db)


@router.get("/{estufa_id}/atuadores/{dispositivo_id}/comandos", response_model=list[HistoricoComandoResposta])
async def historico_comandos(
    estufa_id: str,
    dispositivo_id: str,
    limit: int = 50,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retorna o historico de comandos enviados a um dispositivo.
    Ordenado do mais recente para o mais antigo.
    Reader pode consultar o historico.
    """
    _get_estufa_e_dispositivo(estufa_id, dispositivo_id, user, db)

    rows = (
        db.query(CommandHistory)
        .filter(CommandHistory.dispositivo_id == dispositivo_id)
        .order_by(CommandHistory.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        HistoricoComandoResposta(
            id=row.id,
            dispositivoId=row.dispositivo_id,
            commandType=row.command_type,
            payload=row.payload,
            deliveryMethod=row.delivery_method,
            status=_command_to_status_label(row.status),
            errorMessage=row.error_message,
            responsePayload=row.response_payload,
            sentByUserId=row.sent_by_user_id,
            reason=row.reason,
            createdAt=row.created_at.isoformat() if row.created_at else None,
        )
        for row in rows
    ]


@router.get("/{estufa_id}/atuadores/{dispositivo_id}/status")
async def status_dispositivo(
    estufa_id: str,
    dispositivo_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retorna o status do dispositivo via device twin do IoT Hub.

    Informacoes incluidas:
      - connectionState: Connected / Disconnected
      - lastActivityTime: ultima comunicacao com o IoT Hub
      - desiredProperties: configuracoes desejadas pelo sistema
      - reportedProperties: estado atual relatado pelo dispositivo

    Reader pode consultar o status.
    """
    estufa, dispositivo = _get_estufa_e_dispositivo(estufa_id, dispositivo_id, user, db)

    if not dispositivo.iothub_device_id:
        return {
            "dispositivoId": dispositivo_id,
            "nome": dispositivo.nome,
            "tipo": dispositivo.tipo,
            "ativo": dispositivo.ativo,
            "iothubRegistered": False,
            "message": "Dispositivo nao registrado no IoT Hub.",
        }

    try:
        from app.services.iothub_command_service import get_command_service

        service = get_command_service()
        twin = await service.get_device_twin(dispositivo.iothub_device_id)

        return {
            "dispositivoId": dispositivo_id,
            "nome": dispositivo.nome,
            "tipo": dispositivo.tipo,
            "ativo": dispositivo.ativo,
            "iothubRegistered": True,
            "iothubDeviceId": dispositivo.iothub_device_id,
            "connectionState": twin.get("connectionState"),
            "lastActivityTime": twin.get("lastActivityTime"),
            "desiredProperties": twin.get("desiredProperties", {}),
            "reportedProperties": twin.get("reportedProperties", {}),
        }

    except Exception as exc:
        return {
            "dispositivoId": dispositivo_id,
            "nome": dispositivo.nome,
            "tipo": dispositivo.tipo,
            "ativo": dispositivo.ativo,
            "iothubRegistered": True,
            "iothubDeviceId": dispositivo.iothub_device_id,
            "connectionState": "Unknown",
            "error": str(exc),
        }
