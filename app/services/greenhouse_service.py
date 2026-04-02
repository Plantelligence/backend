"""Servicos de regra de negocio para CRUD de estufas."""

from sqlalchemy.orm import Session
from app.db.postgres.session import get_session
from app.models.estufa import Estufa
from app.models.greenhouse import Greenhouse
from app.models.user import User
from app.schemas.estufa import CriarEstufa, AtualizarEstufa

def _verificar_ownership(estufa: Estufa | None, user_id: str) -> None:
    """Garante que a estufa existe e pertence ao usuario autenticado."""
    if estufa is None:
        raise FileNotFoundError("Estufa nao encontrada.")
    if estufa.user_id != user_id:
        raise PermissionError("Voce nao tem permissao para acessar esta estufa.")

def listar_estufas(db: Session, user_id: str) -> list[Estufa]:
    """Lista apenas as estufas do usuario logado."""
    return db.query(Estufa).filter(Estufa.user_id == user_id).all()

def criar_estufa(db: Session, user_id: str, dados: CriarEstufa) -> Estufa:
    """Cria uma estufa vinculada ao usuario autenticado."""
    nova_estufa = Estufa(
        nome=dados.nome,
        cidade=dados.cidade,
        estado=dados.estado,
        preset_id=dados.preset_id,
        user_id=user_id,
    )
    db.add(nova_estufa)
    db.commit()
    # Recarrega para trazer campos preenchidos pelo banco.
    db.refresh(nova_estufa)
    return nova_estufa

def buscar_estufa(db: Session, estufa_id: str, user_id: str) -> Estufa:
    """Busca uma estufa por id validando permissao de acesso."""
    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    _verificar_ownership(estufa, user_id)
    return estufa

def atualizar_estufa(db: Session, estufa_id: str, user_id: str, dados: AtualizarEstufa) -> Estufa:
    """Atualiza somente os campos enviados para a estufa."""
    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    _verificar_ownership(estufa, user_id)

    # Mantem campos nao enviados intactos.
    campos_para_atualizar = dados.model_dump(exclude_none=True)
    for campo, valor in campos_para_atualizar.items():
        setattr(estufa, campo, valor)

    db.commit()
    db.refresh(estufa)
    return estufa

def deletar_estufa(db: Session, estufa_id: str, user_id: str) -> dict:
    """Remove a estufa do usuario e retorna o id excluido."""
    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    _verificar_ownership(estufa, user_id)

    db.delete(estufa)
    db.commit()
    return {"deletado_id": estufa_id}


def list_greenhouses_for_admin(owner_id: str) -> list[dict]:
    """Lista estufas do owner para uso no painel administrativo."""
    with get_session() as db:
        rows = (
            db.query(Greenhouse)
            .filter(Greenhouse.owner_id == owner_id)
            .order_by(Greenhouse.created_at.desc())
            .all()
        )
    return [row.to_dict() for row in rows]


def get_greenhouse_for_admin(greenhouse_id: str) -> dict:
    """Retorna uma estufa especifica por id para a visao admin."""
    with get_session() as db:
        row = db.query(Greenhouse).filter(Greenhouse.id == greenhouse_id).first()

    if not row:
        raise FileNotFoundError("Estufa nao encontrada.")

    return row.to_dict()


def update_greenhouse_team(payload: dict) -> dict:
    """Atualiza a lista de watchers da estufa no contexto administrativo."""
    greenhouse_id = payload.get("greenhouseId")
    watcher_ids = payload.get("watcherIds") or []

    if not greenhouse_id:
        raise ValueError("greenhouseId e obrigatorio.")

    # Remove duplicidades e valores vazios mantendo ordem de entrada.
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
