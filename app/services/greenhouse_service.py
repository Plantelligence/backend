# CRUD e regras de negócio de estufas

from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.db.postgres.session import get_session
from app.models.estufa import Estufa
from app.models.greenhouse import Greenhouse
from app.models.preset import Preset
from app.models.user import User
from app.schemas.estufa import CriarEstufa, AtualizarEstufa
from app.services import address_service


def _serialize_preset_row(row: tuple | None) -> dict | None:
    if not row:
        return None

    return {
        "id": row[0],
        "sistema": bool(row[1]),
        "user_id": row[2],
        "nome_cultura": row[3],
        "tipo_cultura": row[4],
        "descricao": row[5],
        "temperatura": row[6],
        "umidade": row[7],
        "luminosidade": row[8],
        "created_at": row[9],
        "updated_at": row[10],
    }


def _build_user_map(db: Session, user_ids: set[str]) -> dict[str, dict]:
    if not user_ids:
        return {}

    rows = (
        db.query(User.id, User.full_name, User.email, User.role)
        .filter(User.id.in_(user_ids))
        .all()
    )
    return {
        row[0]: {
            "id": row[0],
            "full_name": row[1],
            "email": row[2],
            "role": row[3],
        }
        for row in rows
    }


def _resolve_watchers_details(watcher_ids: list[str], user_map: dict[str, dict]) -> list[dict]:
    details: list[dict] = []
    for watcher_id in watcher_ids:
        user = user_map.get(watcher_id)
        if not user:
            continue
        details.append(
            {
                "id": user["id"],
                "fullName": user.get("full_name") or user.get("email") or "Colaborador",
                "email": user.get("email"),
                "role": user.get("role"),
            }
        )
    return details


def _serialize_estufa_row(row: tuple, preset_map: dict[str, dict], user_map: dict[str, dict]) -> dict:
    preset_id = row[8]
    watcher_ids = row[9] or []
    return {
        "id": row[0],
        "nome": row[1],
        "estado": row[2],
        "cidade": row[3],
        "cep": row[4],
        "created_at": row[5],
        "updated_at": row[6],
        "user_id": row[7],
        "preset_id": preset_id,
        "responsible_user_ids": watcher_ids,
        "alerts_enabled": bool(row[10]),
        "last_alert_at": row[11],
        "watchers_details": _resolve_watchers_details(watcher_ids, user_map),
        "preset": preset_map.get(preset_id) if preset_id else None,
    }


def _query_estufa_rows(db: Session, filter_clause) -> list[tuple]:
    return (
        db.query(
            Estufa.id,
            Estufa.nome,
            Estufa.estado,
            Estufa.cidade,
            Estufa.cep,
            Estufa.created_at,
            Estufa.updated_at,
            Estufa.user_id,
            Estufa.preset_id,
            Estufa.responsible_user_ids,
            Estufa.alerts_enabled,
            Estufa.last_alert_at,
        )
        .filter(filter_clause)
        .all()
    )


def _build_preset_map(db: Session, preset_ids: set[str]) -> dict[str, dict]:
    if not preset_ids:
        return {}

    rows = (
        db.query(
            Preset.id,
            Preset.sistema,
            Preset.user_id,
            Preset.nome_cultura,
            Preset.tipo_cultura,
            Preset.descricao,
            Preset.temperatura,
            Preset.umidade,
            Preset.luminosidade,
            Preset.created_at,
            Preset.updated_at,
        )
        .filter(Preset.id.in_(preset_ids))
        .all()
    )
    return {row[0]: _serialize_preset_row(row) for row in rows}


def _serialize_estufa_rows(db: Session, rows: list[tuple]) -> list[dict]:
    preset_ids = {row[8] for row in rows if row[8]}
    watcher_ids = {
        watcher_id
        for row in rows
        for watcher_id in (row[9] or [])
        if watcher_id
    }
    preset_map = _build_preset_map(db, preset_ids)
    user_map = _build_user_map(db, watcher_ids)
    return [_serialize_estufa_row(row, preset_map, user_map) for row in rows]


def _fetch_estufa_payload(db: Session, estufa_id: str) -> dict | None:
    rows = _query_estufa_rows(db, Estufa.id == estufa_id)
    if not rows:
        return None
    return _serialize_estufa_rows(db, rows)[0]

def _verificar_ownership(estufa: Estufa | None, user_id: str) -> None:
    if estufa is None:
        raise FileNotFoundError("Estufa nao encontrada.")
    if estufa.user_id != user_id:
        raise PermissionError("Voce nao tem permissao para acessar esta estufa.")


def _can_access_greenhouse_ids(estufa_id: str | None, estufa_user_id: str | None, user: dict) -> bool:
    if not estufa_id or not estufa_user_id:
        return False

    role = (user.get("role") or "").strip()
    owner_scope = (user.get("organizationOwnerId") or user.get("id") or "").strip()
    org_key = (user.get("organizationKey") or "").strip()

    if role in ("Admin", "Collaborator"):
        if not owner_scope and not org_key:
            return estufa_user_id == user.get("id")
        return _is_member_in_owner_scope(estufa_user_id, owner_scope, org_key)

    if role == "Reader":
        allowed_ids = ((user.get("permissions") or {}).get("allowedGreenhouseIds") or [])
        return estufa_id in allowed_ids

    return estufa_user_id == user.get("id")

def listar_estufas(db: Session, user: dict) -> list[dict]:
    role = (user.get("role") or "").strip()
    owner_scope = (user.get("organizationOwnerId") or user.get("id") or "").strip()
    org_key = (user.get("organizationKey") or "").strip()
    org_member_ids = _list_member_ids(db, owner_scope, org_key)

    if role in ("Admin", "Collaborator"):
        if not org_member_ids:
            return []
        rows = _query_estufa_rows(db, Estufa.user_id.in_(org_member_ids))
        return _serialize_estufa_rows(db, rows)

    if role == "Reader":
        allowed_ids = ((user.get("permissions") or {}).get("allowedGreenhouseIds") or [])
        if not allowed_ids:
            return []
        rows = _query_estufa_rows(db, Estufa.id.in_(allowed_ids))
        return _serialize_estufa_rows(db, rows)

    rows = _query_estufa_rows(db, Estufa.user_id == user.get("id"))
    return _serialize_estufa_rows(db, rows)


def _list_member_ids(db: Session, owner_scope: str, org_key: str = "") -> list[str]:
    if not owner_scope and not org_key:
        return []
    query = db.query(User.id)
    if owner_scope and org_key:
        query = query.filter(or_(User.organization_owner_id == owner_scope, User.organization_key == org_key))
    elif owner_scope:
        query = query.filter(User.organization_owner_id == owner_scope)
    else:
        query = query.filter(User.organization_key == org_key)

    rows = query.all()
    member_ids = [row[0] for row in rows]
    if owner_scope not in member_ids:
        member_ids.append(owner_scope)
    return member_ids


def _is_member_in_owner_scope(user_id: str, owner_scope: str, org_key: str = "") -> bool:
    if (not owner_scope and not org_key) or not user_id:
        return False
    with get_session() as db:
        query = db.query(User.id).filter(User.id == user_id)
        if owner_scope and org_key:
            query = query.filter(or_(User.organization_owner_id == owner_scope, User.organization_key == org_key))
        elif owner_scope:
            query = query.filter(User.organization_owner_id == owner_scope)
        else:
            query = query.filter(User.organization_key == org_key)

        row = query.first()
        return bool(row)

def criar_estufa(db: Session, user: dict, dados: CriarEstufa) -> dict:
    if (user.get("role") or "").strip() == "Reader":
        raise PermissionError("Perfil Leitor nao pode criar estufas.")

    user_id = user.get("id")
    if not user_id:
        raise PermissionError("Usuario invalido para criacao de estufa.")

    endereco: dict[str, str] = {}
    try:
        endereco = address_service.resolve_cep_location(dados.cep)
    except Exception:
        endereco = {"cep": dados.cep}  # ViaCEP fora do ar; segue sem cidade/estado

    cidade = (endereco.get("cidade") or (dados.cidade or "")).strip()
    estado = (endereco.get("estado") or (dados.estado or "")).strip().upper()

    if not cidade or len(estado) != 2:
        raise ValueError("Informe cidade e estado validos (UF com 2 letras) para concluir o cadastro da estufa.")

    nova_estufa = Estufa(
        nome=dados.nome,
        cidade=cidade,
        estado=estado,
        cep=endereco.get("cep"),
        preset_id=dados.preset_id,
        user_id=user_id,
    )
    db.add(nova_estufa)
    db.flush()
    estufa_id = nova_estufa.id
    db.commit()
    criada = _fetch_estufa_payload(db, estufa_id)
    if not criada:
        raise FileNotFoundError("Estufa nao encontrada apos criacao.")
    return criada

def buscar_estufa(db: Session, estufa_id: str, user: dict) -> dict:
    estufa = _fetch_estufa_payload(db, estufa_id)
    if estufa is None:
        raise FileNotFoundError("Estufa nao encontrada.")
    if not _can_access_greenhouse_ids(estufa.get("id"), estufa.get("user_id"), user):
        raise PermissionError("Voce nao tem permissao para acessar esta estufa.")
    return estufa

def atualizar_estufa(db: Session, estufa_id: str, user: dict, dados: AtualizarEstufa) -> dict:
    if (user.get("role") or "").strip() == "Reader":
        raise PermissionError("Perfil Leitor nao pode editar estufas.")

    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    if estufa is None:
        raise FileNotFoundError("Estufa nao encontrada.")
    if not _can_access_greenhouse_ids(estufa.id, estufa.user_id, user):
        raise PermissionError("Voce nao tem permissao para acessar esta estufa.")

    previous_preset_id = estufa.preset_id

    # Mantem campos nao enviados intactos.
    campos_para_atualizar = dados.model_dump(exclude_none=True)

    if "responsible_user_ids" in campos_para_atualizar:
        campos_para_atualizar["responsible_user_ids"] = sanitize_responsible_user_ids(
            db,
            user,
            campos_para_atualizar.get("responsible_user_ids") or [],
        )

    if "cep" in campos_para_atualizar:
        try:
            endereco = address_service.resolve_cep_location(campos_para_atualizar.get("cep") or "")
            campos_para_atualizar["cep"] = endereco.get("cep")
            campos_para_atualizar["cidade"] = endereco.get("cidade")
            campos_para_atualizar["estado"] = endereco.get("estado")
        except Exception:
            pass  # ViaCEP fora do ar; mantém o CEP digitado

    if "estado" in campos_para_atualizar and campos_para_atualizar.get("estado"):
        campos_para_atualizar["estado"] = str(campos_para_atualizar["estado"]).strip().upper()

    for campo, valor in campos_para_atualizar.items():
        setattr(estufa, campo, valor)

    # preset trocado → zera cooldown para alertar na próxima avaliação
    if "preset_id" in campos_para_atualizar and estufa.preset_id != previous_preset_id:
        estufa.last_alert_at = None

    db.commit()
    atualizada = _fetch_estufa_payload(db, estufa_id)
    if not atualizada:
        raise FileNotFoundError("Estufa nao encontrada.")
    return atualizada

def deletar_estufa(db: Session, estufa_id: str, user: dict) -> dict[str, str]:
    if (user.get("role") or "").strip() == "Reader":
        raise PermissionError("Perfil Leitor nao pode excluir estufas.")

    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    if estufa is None:
        raise FileNotFoundError("Estufa nao encontrada.")
    if not _can_access_greenhouse_ids(estufa.id, estufa.user_id, user):
        raise PermissionError("Voce nao tem permissao para acessar esta estufa.")

    db.delete(estufa)
    db.commit()
    return {"deletado_id": estufa_id}


def sanitize_responsible_user_ids(db: Session, user: dict, user_ids: list[str]) -> list[str]:
    owner_scope = (user.get("organizationOwnerId") or user.get("id") or "").strip()
    org_key = (user.get("organizationKey") or "").strip()
    allowed_ids = set(_list_member_ids(db, owner_scope, org_key))

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_user_id in user_ids:
        user_id = (raw_user_id or "").strip()
        if not user_id or user_id in seen:
            continue
        if user_id in allowed_ids:
            seen.add(user_id)
            cleaned.append(user_id)
    return cleaned


def update_estufa_responsibles(db: Session, estufa_id: str, user: dict, responsible_user_ids: list[str]) -> dict:
    if (user.get("role") or "").strip() == "Reader":
        raise PermissionError("Perfil Leitor nao pode delegar responsaveis da estufa.")

    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    if estufa is None:
        raise FileNotFoundError("Estufa nao encontrada.")
    if not _can_access_greenhouse_ids(estufa.id, estufa.user_id, user):
        raise PermissionError("Voce nao tem permissao para acessar esta estufa.")

    estufa.responsible_user_ids = sanitize_responsible_user_ids(db, user, responsible_user_ids)
    db.commit()

    atualizada = _fetch_estufa_payload(db, estufa_id)
    if not atualizada:
        raise FileNotFoundError("Estufa nao encontrada.")
    return atualizada


def update_estufa_alerts(db: Session, estufa_id: str, user: dict, enabled: bool) -> dict:
    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    if estufa is None:
        raise FileNotFoundError("Estufa nao encontrada.")
    if not _can_access_greenhouse_ids(estufa.id, estufa.user_id, user):
        raise PermissionError("Voce nao tem permissao para acessar esta estufa.")

    estufa.alerts_enabled = bool(enabled)
    db.commit()

    atualizada = _fetch_estufa_payload(db, estufa_id)
    if not atualizada:
        raise FileNotFoundError("Estufa nao encontrada.")
    return atualizada


def list_available_responsibles(db: Session, user: dict) -> list[dict]:
    owner_scope = (user.get("organizationOwnerId") or user.get("id") or "").strip()
    if not owner_scope:
        return []

    rows = (
        db.query(User.id, User.full_name, User.email, User.role)
        .filter(or_(User.organization_owner_id == owner_scope, User.id == owner_scope))
        .order_by(User.full_name.asc(), User.email.asc())
        .all()
    )
    return [
        {
            "id": row[0],
            "fullName": row[1] or row[2] or "Colaborador",
            "email": row[2],
            "role": row[3],
        }
        for row in rows
    ]


def mark_last_alert_sent(db: Session, estufa_id: str) -> None:
    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    if not estufa:
        return
    estufa.last_alert_at = datetime.now(timezone.utc).isoformat()
    db.commit()


def list_greenhouses_for_admin(owner_id: str) -> list[dict]:
    with get_session() as db:
        rows = (
            db.query(Greenhouse)
            .filter(Greenhouse.owner_id == owner_id)
            .order_by(Greenhouse.created_at.desc())
            .all()
        )
        return [row.to_dict() for row in rows]


def get_greenhouse_for_admin(greenhouse_id: str) -> dict:
    with get_session() as db:
        row = db.query(Greenhouse).filter(Greenhouse.id == greenhouse_id).first()
        if not row:
            raise FileNotFoundError("Estufa nao encontrada.")
        return row.to_dict()


def update_greenhouse_team(payload: dict) -> dict:
    greenhouse_id = payload.get("greenhouseId")
    watcher_ids = payload.get("watcherIds") or []

    if not greenhouse_id:
        raise ValueError("greenhouseId e obrigatorio.")

    # deduplica mantendo a ordem de entrada
    cleaned_watcher_ids: list[str] = []
    seen: set[str] = set()
    for watcher_id in watcher_ids:
        value = (watcher_id or "").strip()
        if value and value not in seen:
            seen.add(value)
            cleaned_watcher_ids.append(value)

    with get_session() as db:
        greenhouse = db.query(Greenhouse).filter(Greenhouse.id == greenhouse_id).first()
        if not greenhouse:
            raise FileNotFoundError("Estufa nao encontrada.")

        if cleaned_watcher_ids:
            existing_users = (
                db.query(User.id)
                .filter(User.id.in_(cleaned_watcher_ids))
                .all()
            )
            valid_ids = {row[0] for row in existing_users}
            cleaned_watcher_ids = [wid for wid in cleaned_watcher_ids if wid in valid_ids]

        greenhouse.watchers = cleaned_watcher_ids

    return get_greenhouse_for_admin(greenhouse_id)
