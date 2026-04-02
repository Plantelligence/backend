"""Servicos de regra de negocio para CRUD de estufas."""

from sqlalchemy.orm import Session
from app.models.estufa import Estufa
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
