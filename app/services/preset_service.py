# presets de cultivo: seed, listagem e CRUD do usuário

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.preset import Preset
from app.models.user import User
from app.schemas.preset import CriarPresetUsuario, AtualizarPresetUsuario
from typing import Any
from app.models.estufa import Estufa


presets_cogumelos: list[dict[str, Any]] = [
    {
        "id": "shiitake",
        "sistema": True,
        "user_id": None,
        "nome_cultura": "Shiitake",
        "tipo_cultura": "Cogumelos",
        "descricao": "Lentinula edodes em fase de frutificacao, com alta umidade e ventilacao controlada.",
        "temperatura": {
            "critico_baixo": {"min": 8, "max": 11},
            "alerta_baixo": {"min": 11, "max": 13},
            "ideal": {"min": 13, "max": 18},
            "alerta_alto": {"min": 18, "max": 21},
            "critico_alto": {"min": 21, "max": 28},
        },
        "umidade": {
            "critico_baixo": {"min": 65, "max": 75},
            "alerta_baixo": {"min": 75, "max": 82},
            "ideal": {"min": 82, "max": 92},
            "alerta_alto": {"min": 92, "max": 96},
            "critico_alto": {"min": 96, "max": 100},
        },
        "luminosidade": {
            "critico_baixo": {"min": 0, "max": 80},
            "alerta_baixo": {"min": 80, "max": 120},
            "ideal": {"min": 120, "max": 400},
            "alerta_alto": {"min": 400, "max": 700},
            "critico_alto": {"min": 700, "max": 1500},
        },
    },
    {
        "id": "shimeji",
        "sistema": True,
        "user_id": None,
        "nome_cultura": "Shimeji",
        "tipo_cultura": "Cogumelos",
        "descricao": "Shimeji (Hypsizygus tessellatus) em fase de frutificacao, ambiente fresco e umido.",
        "temperatura": {
            "critico_baixo": {"min": 8, "max": 12},
            "alerta_baixo": {"min": 12, "max": 14},
            "ideal": {"min": 14, "max": 18},
            "alerta_alto": {"min": 18, "max": 21},
            "critico_alto": {"min": 21, "max": 28},
        },
        "umidade": {
            "critico_baixo": {"min": 68, "max": 78},
            "alerta_baixo": {"min": 78, "max": 84},
            "ideal": {"min": 84, "max": 92},
            "alerta_alto": {"min": 92, "max": 96},
            "critico_alto": {"min": 96, "max": 100},
        },
        "luminosidade": {
            "critico_baixo": {"min": 0, "max": 120},
            "alerta_baixo": {"min": 120, "max": 180},
            "ideal": {"min": 180, "max": 500},
            "alerta_alto": {"min": 500, "max": 750},
            "critico_alto": {"min": 750, "max": 1500},
        },
    },
    {
        "id": "champignon",
        "sistema": True,
        "user_id": None,
        "nome_cultura": "Champignon",
        "tipo_cultura": "Cogumelos",
        "descricao": "Agaricus bisporus em fase de frutificacao com ambiente fresco e umidade elevada.",
        "temperatura": {
            "critico_baixo": {"min": 8, "max": 12},
            "alerta_baixo": {"min": 12, "max": 15},
            "ideal": {"min": 15, "max": 19},
            "alerta_alto": {"min": 19, "max": 22},
            "critico_alto": {"min": 22, "max": 30},
        },
        "umidade": {
            "critico_baixo": {"min": 70, "max": 80},
            "alerta_baixo": {"min": 80, "max": 86},
            "ideal": {"min": 86, "max": 93},
            "alerta_alto": {"min": 93, "max": 97},
            "critico_alto": {"min": 97, "max": 100},
        },
        "luminosidade": {
            "critico_baixo": {"min": 0, "max": 80},
            "alerta_baixo": {"min": 80, "max": 120},
            "ideal": {"min": 120, "max": 350},
            "alerta_alto": {"min": 350, "max": 600},
            "critico_alto": {"min": 600, "max": 1500},
        },
    },
]
def seed_presets(db: Session) -> None:
    for preset in presets_cogumelos:
        existente = db.query(Preset).filter(Preset.id == preset["id"]).first()
        if not existente:
            db.add(Preset(**preset))
        else:
            existente.sistema = preset["sistema"]
            existente.user_id = preset["user_id"]
            existente.nome_cultura = preset["nome_cultura"]
            existente.tipo_cultura = preset["tipo_cultura"]
            existente.descricao = preset["descricao"]
            existente.temperatura = preset["temperatura"]
            existente.umidade = preset["umidade"]
            existente.luminosidade = preset["luminosidade"]

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existente = db.query(Preset).filter(Preset.id == preset["id"]).first()
            if existente:
                existente.sistema = preset["sistema"]
                existente.user_id = preset["user_id"]
                existente.nome_cultura = preset["nome_cultura"]
                existente.tipo_cultura = preset["tipo_cultura"]
                existente.descricao = preset["descricao"]
                existente.temperatura = preset["temperatura"]
                existente.umidade = preset["umidade"]
                existente.luminosidade = preset["luminosidade"]
                db.commit()

def listar_presets(db: Session, user_id: str) -> list[Preset]:
    return (
        db.query(Preset)
        .filter((Preset.sistema == True) | (Preset.user_id == user_id))
        .order_by(Preset.sistema.desc(), Preset.nome_cultura.asc())
        .all()
    )

def buscar_preset_por_id(db: Session, id: str) -> Preset | None:
    return db.query(Preset).filter(Preset.id == id).first()

def buscar_preset_por_nome(db: Session, nome: str) -> Preset | None:
    return db.query(Preset).filter(Preset.nome_cultura == nome).first()

def vincular_preset_a_estufa(db: Session, estufa_id: str, preset_id: str, user: dict) -> None:
    role = (user.get("role") or "").strip()
    actor_id = (user.get("id") or "").strip()
    owner_scope = (user.get("organizationOwnerId") or actor_id or "").strip()

    if role == "Reader":
        raise PermissionError("Perfil Leitor possui acesso somente de consulta.")

    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    if not estufa:
        raise ValueError("Estufa nao encontrada")

    if role in ("Admin", "Collaborator"):
        allowed_member_ids = [row[0] for row in db.query(User.id).filter(User.organization_owner_id == owner_scope).all()]
        if owner_scope not in allowed_member_ids:
            allowed_member_ids.append(owner_scope)
        if estufa.user_id not in allowed_member_ids:
            raise PermissionError("Voce nao tem permissao para alterar esta estufa")
    elif estufa.user_id != actor_id:
        raise PermissionError("Voce nao tem permissao para alterar esta estufa")
        
    preset = db.query(Preset).filter(Preset.id == preset_id).first()
    if not preset:
        raise ValueError("Preset nao encontrado")
        
    estufa.preset_id = preset_id
    db.commit()


def criar_preset_usuario(db: Session, user_id: str, dados: CriarPresetUsuario) -> Preset:
    preset = Preset(
        sistema=False,
        user_id=user_id,
        nome_cultura=dados.nome_cultura.strip(),
        tipo_cultura=dados.tipo_cultura.strip(),
        descricao=dados.descricao,
        temperatura=dados.temperatura.model_dump(),
        umidade=dados.umidade.model_dump(),
        luminosidade=dados.luminosidade.model_dump(),
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return preset


def _buscar_preset_editavel(db: Session, preset_id: str, user_id: str) -> Preset:
    preset = db.query(Preset).filter(Preset.id == preset_id).first()
    if not preset:
        raise ValueError("Preset nao encontrado")
    if preset.sistema:
        raise PermissionError("Presets padrao do sistema nao podem ser alterados")
    if preset.user_id != user_id:
        raise PermissionError("Voce nao tem permissao para alterar este preset")
    return preset


def atualizar_preset_usuario(
    db: Session,
    preset_id: str,
    user_id: str,
    dados: AtualizarPresetUsuario,
) -> Preset:
    preset = _buscar_preset_editavel(db, preset_id, user_id)

    updates = dados.model_dump(exclude_unset=True)

    if "nome_cultura" in updates:
        preset.nome_cultura = str(updates["nome_cultura"]).strip()
    if "tipo_cultura" in updates:
        preset.tipo_cultura = str(updates["tipo_cultura"]).strip()
    if "descricao" in updates:
        preset.descricao = updates["descricao"]
    if "temperatura" in updates:
        preset.temperatura = updates["temperatura"]
    if "umidade" in updates:
        preset.umidade = updates["umidade"]
    if "luminosidade" in updates:
        preset.luminosidade = updates["luminosidade"]

    db.commit()
    db.refresh(preset)
    return preset


def remover_preset_usuario(db: Session, preset_id: str, user_id: str) -> None:
    preset = _buscar_preset_editavel(db, preset_id, user_id)

    # desvincula manualmente; ON DELETE SET NULL pode não estar aplicado no banco
    for estufa in preset.estufas:
        estufa.preset_id = None

    db.delete(preset)
    db.commit()