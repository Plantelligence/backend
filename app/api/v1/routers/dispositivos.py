"""
Rotas CRUD para gerenciamento de dispositivos IoT vinculados às estufas.

Dispositivos representam o hardware físico conectado às estufas: sensores
(temperatura, umidade, solo, luminosidade) e atuadores (ventilação, irrigação,
iluminação). Cada dispositivo é registrado automaticamente no Azure IoT Hub
no momento da criação, recebendo credenciais MQTT únicas.

Fluxo de criação de um dispositivo:
  1. Usuário preenche o formulário no frontend com nome e tipo;
  2. O backend valida o acesso do usuário à estufa;
  3. O sistema chama o IoT Hub e registra o dispositivo lá;
  4. O IoT Hub retorna as credenciais (device ID, chave, SAS Token);
  5. O backend salva no banco e retorna as credenciais para o frontend;
  6. O usuário copia essas credenciais para o arquivo boot.py do ESP32.

Endpoints disponíveis:
  GET    /api/estufas/{estufa_id}/dispositivos                           — lista dispositivos
  POST   /api/estufas/{estufa_id}/dispositivos                           — cria dispositivo
  PATCH  /api/estufas/{estufa_id}/dispositivos/{id}                      — atualiza nome/status
  DELETE /api/estufas/{estufa_id}/dispositivos/{id}                      — remove dispositivo
  POST   /api/estufas/{estufa_id}/dispositivos/{id}/regenerar-token      — renova SAS Token

Controle de acesso:
  - Proprietário da estufa, responsáveis cadastrados e Admins têm acesso completo;
  - Perfil "Reader" pode visualizar mas não criar, editar ou remover;
  - Outros usuários recebem HTTP 403 (acesso negado).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.core.dependencies import get_current_user, get_db
from app.models.dispositivo import Dispositivo
from app.models.estufa import Estufa
from app.schemas.dispositivo import AtualizarDispositivo, CriarDispositivo, DispositivoResposta

router = APIRouter(prefix="/api/estufas", tags=["Dispositivos"])


def _get_estufa_acessivel(estufa_id: str, user: dict[str, Any], db: Session) -> Estufa:
    """
    Carrega a estufa do banco e verifica se o usuário tem permissão de acesso.
    Lança HTTP 404 se não existir ou HTTP 403 se não tiver acesso.

    Tem acesso: dono da estufa, responsáveis listados em responsible_user_ids,
    e usuários com perfil Admin.
    """
    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    if not estufa:
        raise HTTPException(status_code=404, detail="Estufa não encontrada.")
    responsaveis = estufa.responsible_user_ids or []
    tem_acesso = (
        estufa.user_id == user["id"]
        or user["id"] in responsaveis
        or user.get("role") == "Admin"
    )
    if not tem_acesso:
        raise HTTPException(status_code=403, detail="Acesso negado a esta estufa.")
    return estufa


def _to_resposta(d: Dispositivo, iothub_credentials: dict | None = None) -> DispositivoResposta:
    """
    Converte o modelo de banco de dados em um objeto de resposta da API.

    O SAS Token de autenticação MQTT nunca é armazenado no banco de dados
    por segurança — ele é retornado apenas no momento da criação ou na
    renovação explícita. Por isso, iothub_credentials é passado separado.
    Os campos MQTT (servidor, porta, usuário, tópicos) são montados dinamicamente
    a partir das configurações e do device ID registrado no IoT Hub.
    """
    hub_host = settings.iothub_host or ""
    data = {
        "id": d.id,
        "nome": d.nome,
        "tipo": d.tipo,
        "identificador": d.identificador,
        "ativo": d.ativo,
        "estufa_id": d.estufa_id,
        "iothub_device_id": d.iothub_device_id,
        # SAS token só é retornado na criação (via iothub_credentials); nunca do banco
        "iothub_sas_token": (iothub_credentials or {}).get("iothub_sas_token"),
        "mqtt_server":    hub_host or None,
        "mqtt_port":      8883 if hub_host else None,
        "mqtt_username":  (f"{hub_host}/{d.iothub_device_id}/?api-version=2021-04-12") if d.iothub_device_id and hub_host else None,
        "mqtt_topic_pub": (f"devices/{d.iothub_device_id}/messages/events/") if d.iothub_device_id else None,
        "mqtt_topic_sub": (f"devices/{d.iothub_device_id}/messages/devicebound/#") if d.iothub_device_id else None,
    }
    return DispositivoResposta(**data)


@router.get("/{estufa_id}/dispositivos")
async def listar_dispositivos(
    estufa_id: str,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Retorna todos os dispositivos cadastrados em uma estufa."""
    _get_estufa_acessivel(estufa_id, user, db)
    dispositivos = db.query(Dispositivo).filter(Dispositivo.estufa_id == estufa_id).all()
    return {"dispositivos": [_to_resposta(d) for d in dispositivos]}


@router.post("/{estufa_id}/dispositivos", status_code=status.HTTP_201_CREATED)
async def criar_dispositivo(
    estufa_id: str,
    payload: CriarDispositivo,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(get_current_user),
):
    """
    Cadastra um dispositivo no Plantelligence e o registra no Azure IoT Hub.

    Retorna as credenciais MQTT completas para configurar no ESP32:
      - iothub_device_id: ID único do dispositivo no IoT Hub
      - iothub_sas_token: senha MQTT com validade de 1 ano
      - mqtt_server, mqtt_port, mqtt_username, mqtt_topic_pub, mqtt_topic_sub

    Se o IoT Hub estiver indisponível, o dispositivo é criado no banco sem credenciais
    (falha silenciosa) — pode ser tentado novamente mais tarde.
    """
    if user.get("role") == "Reader":
        raise HTTPException(status_code=403, detail="Perfil Leitor não pode adicionar dispositivos.")

    _get_estufa_acessivel(estufa_id, user, db)

    # gera identificador único: usa o fornecido pelo usuário ou cria um automático
    suffix = str(uuid.uuid4())[:8]
    identificador = payload.identificador or f"device-{suffix}"

    existente = db.query(Dispositivo).filter(Dispositivo.identificador == identificador).first()
    if existente:
        raise HTTPException(status_code=409, detail="Já existe um dispositivo com esse identificador.")

    # ── Registro no Azure IoT Hub ─────────────────────────────────────────────
    iothub_credentials: dict | None = None
    if settings.iothub_connection_string:
        try:
            from app.services.iothub_registry import create_device as iothub_create
            iothub_credentials = await iothub_create(payload.nome, suffix)
        except Exception as exc:
            # não bloqueia o cadastro se o IoT Hub estiver temporariamente indisponível
            print(f"[dispositivos] Aviso: IoT Hub indisponível ({exc}). Dispositivo criado sem credenciais.")

    # salva no banco de dados PostgreSQL
    dispositivo = Dispositivo(
        id=str(uuid.uuid4()),
        nome=payload.nome,
        tipo=payload.tipo,
        identificador=identificador,
        ativo=True,
        estufa_id=estufa_id,
        iothub_device_id=(iothub_credentials or {}).get("iothub_device_id"),
        iothub_primary_key=(iothub_credentials or {}).get("iothub_primary_key"),
        iothub_sas_token=None,  # SAS token não é persistido — regenerado quando necessário
    )
    db.add(dispositivo)
    db.commit()
    db.refresh(dispositivo)
    return _to_resposta(dispositivo, iothub_credentials)


@router.patch("/{estufa_id}/dispositivos/{dispositivo_id}")
async def atualizar_dispositivo(
    estufa_id: str,
    dispositivo_id: str,
    payload: AtualizarDispositivo,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(get_current_user),
):
    """
    Atualiza o nome ou o status ativo/inativo de um dispositivo.
    Apenas esses dois campos podem ser alterados após o cadastro.
    """
    if user.get("role") == "Reader":
        raise HTTPException(status_code=403, detail="Perfil Leitor não pode editar dispositivos.")

    _get_estufa_acessivel(estufa_id, user, db)

    dispositivo = db.query(Dispositivo).filter(
        Dispositivo.id == dispositivo_id,
        Dispositivo.estufa_id == estufa_id,
    ).first()
    if not dispositivo:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado.")

    if payload.nome is not None:
        dispositivo.nome = payload.nome
    if payload.ativo is not None:
        dispositivo.ativo = payload.ativo

    db.commit()
    db.refresh(dispositivo)
    return _to_resposta(dispositivo)


@router.delete("/{estufa_id}/dispositivos/{dispositivo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remover_dispositivo(
    estufa_id: str,
    dispositivo_id: str,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(get_current_user),
):
    """
    Remove o dispositivo do banco de dados e do Azure IoT Hub.
    O ESP32 vinculado a este dispositivo perderá acesso ao IoT Hub após a exclusão.
    A remoção do IoT Hub é feita de forma silenciosa — erros não bloqueiam a exclusão local.
    """
    if user.get("role") == "Reader":
        raise HTTPException(status_code=403, detail="Perfil Leitor não pode remover dispositivos.")

    _get_estufa_acessivel(estufa_id, user, db)

    dispositivo = db.query(Dispositivo).filter(
        Dispositivo.id == dispositivo_id,
        Dispositivo.estufa_id == estufa_id,
    ).first()
    if not dispositivo:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado.")

    # tenta remover do IoT Hub; falha silenciosa para não bloquear a exclusão local
    if dispositivo.iothub_device_id:
        try:
            from app.services.iothub_registry import delete_device as iothub_delete
            await iothub_delete(dispositivo.iothub_device_id)
        except Exception as exc:
            print(f"[dispositivos] Aviso: falha ao remover do IoT Hub ({exc}).")

    db.delete(dispositivo)
    db.commit()


@router.post("/{estufa_id}/dispositivos/{dispositivo_id}/regenerar-token", status_code=status.HTTP_200_OK)
async def regenerar_sas_token(
    estufa_id: str,
    dispositivo_id: str,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(get_current_user),
):
    """
    Gera um novo SAS Token para o dispositivo se conectar ao IoT Hub.

    O SAS Token tem validade de 1 ano. Quando expirar, o ESP32 não conseguirá
    mais enviar dados via MQTT. Use este endpoint para renovar o token e
    depois atualize o arquivo boot.py do ESP32 com o novo valor.

    Retorna as mesmas credenciais MQTT da criação, exceto a chave primária.
    """
    if user.get("role") == "Reader":
        raise HTTPException(status_code=403, detail="Perfil Leitor não pode regenerar tokens.")

    _get_estufa_acessivel(estufa_id, user, db)

    dispositivo = db.query(Dispositivo).filter(
        Dispositivo.id == dispositivo_id,
        Dispositivo.estufa_id == estufa_id,
    ).first()
    if not dispositivo:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado.")

    if not dispositivo.iothub_device_id or not dispositivo.iothub_primary_key:
        raise HTTPException(status_code=400, detail="Dispositivo não possui credenciais IoT Hub.")

    from app.services.iothub_registry import device_sas_token
    sas_token = device_sas_token(dispositivo.iothub_device_id, dispositivo.iothub_primary_key)

    return {
        "iothub_device_id": dispositivo.iothub_device_id,
        "iothub_sas_token": sas_token,
        "mqtt_server":    settings.iothub_host,
        "mqtt_port":      8883,
        "mqtt_username":  f"{settings.iothub_host}/{dispositivo.iothub_device_id}/?api-version=2021-04-12",
        "mqtt_topic_pub": f"devices/{dispositivo.iothub_device_id}/messages/events/",
        "mqtt_topic_sub": f"devices/{dispositivo.iothub_device_id}/messages/devicebound/#",
    }
