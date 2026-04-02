"""Service de gerenciamento de presets de cultivo.

Presets do sistema:
    Sao definidos na lista `presets_cogumelos` e inseridos no banco
    uma unica vez via seed_presets(), chamado no startup do FastAPI.
    Nao podem ser editados ou removidos pelo usuario.

Presets personalizados (feature futura):
    Serao gerados via API do Groq (IA) e salvos com sistema=False
    e user_id preenchido — mesma tabela, diferenciados pelo flag `sistema`.

Funcoes publicas:
    seed_presets        - insere presets fixos no banco (idempotente)
    listar_presets      - retorna todos os presets
    buscar_preset_por_id   - busca por UUID
    buscar_preset_por_nome - busca por nome da cultura
    vincular_preset_a_estufa - vincula preset a uma estufa
"""

from sqlalchemy.orm import Session
from app.models.preset import Preset
from app.schemas.preset import PresetResposta
from typing import Any
from app.models.estufa import Estufa


presets_cogumelos: list[dict[str, Any]] = [
    {
        "id": "1",
        "nome_cultura": "Cogumelos Shiitake - Frutificação",
        "tipo_cultura": "Cogumelos",
        "descricao": "Cultivo de cogumelos shiitake na fase de frutificação.",
        "temperatura": {
            "critico_baixo": {"min": 15, "max": 17},
            "alerta_baixo": {"min": 17, "max": 20},
            "ideal": {"min": 20, "max": 23},
            "alerta_alto": {"min": 23, "max": 25},
            "critico_alto": {"min": 25, "max": 27},
        },
        "umidade": {
            "critico_baixo": {"min": 50, "max": 55},
            "alerta_baixo": {"min": 55, "max": 60},
            "ideal": {"min": 60, "max": 65},
            "alerta_alto": {"min": 65, "max": 70},
            "critico_alto": {"min": 70, "max": 75},
        },
        "luminosidade": {
            "critico_baixo": {"min": 15, "max": 17},
            "alerta_baixo": {"min": 17, "max": 20},
            "ideal": {"min": 20, "max": 23},
            "alerta_alto": {"min": 23, "max": 25},
            "critico_alto": {"min": 25, "max": 27},
        },
    },
    {
        "id": "2",
        "nome_cultura": "Cogumelos Shiitake - Micélio",
        "tipo_cultura": "Cogumelos",
        "descricao": "Cultivo de cogumelos shiitake na fase de micélio.",
        "temperatura": {
            "critico_baixo": {"min": 15, "max": 17},
            "alerta_baixo": {"min": 17, "max": 20},
            "ideal": {"min": 20, "max": 23},
            "alerta_alto": {"min": 23, "max": 25},
            "critico_alto": {"min": 25, "max": 27},
        },
        "umidade": {
            "critico_baixo": {"min": 50, "max": 55},
            "alerta_baixo": {"min": 55, "max": 60},
            "ideal": {"min": 60, "max": 65},
            "alerta_alto": {"min": 65, "max": 70},
            "critico_alto": {"min": 70, "max": 75},
        },
        "luminosidade": {
            "critico_baixo": {"min": 15, "max": 17},
            "alerta_baixo": {"min": 17, "max": 20},
            "ideal": {"min": 20, "max": 23},
            "alerta_alto": {"min": 23, "max": 25},
            "critico_alto": {"min": 25, "max": 27},
        },
    },
    {
        "id": "3",
        "nome_cultura": "Cogumelos Shimeji - Frutificação",
        "tipo_cultura": "Cogumelos",
        "descricao": "Cultivo de cogumelos shiitake na fase de frutificação.",
        "temperatura": {
            "critico_baixo": {"min": 15, "max": 17},
            "alerta_baixo": {"min": 17, "max": 20},
            "ideal": {"min": 20, "max": 23},
            "alerta_alto": {"min": 23, "max": 25},
            "critico_alto": {"min": 25, "max": 27},
        },
        "umidade": {
            "critico_baixo": {"min": 50, "max": 55},
            "alerta_baixo": {"min": 55, "max": 60},
            "ideal": {"min": 60, "max": 65},
            "alerta_alto": {"min": 65, "max": 70},
            "critico_alto": {"min": 70, "max": 75},
        },
        "luminosidade": {
            "critico_baixo": {"min": 15, "max": 17},
            "alerta_baixo": {"min": 17, "max": 20},
            "ideal": {"min": 20, "max": 23},
            "alerta_alto": {"min": 23, "max": 25},
            "critico_alto": {"min": 25, "max": 27},
        },
    },
    {
        "id": "4",
        "nome_cultura": "Cogumelos Shimeji - Micélio",
        "tipo_cultura": "Cogumelos",
        "descricao": "Cultivo de cogumelos shimeji na fase de micélio.",
        "temperatura": {
            "critico_baixo": {"min": 15, "max": 17},
            "alerta_baixo": {"min": 17, "max": 20},
            "ideal": {"min": 20, "max": 23},
            "alerta_alto": {"min": 23, "max": 25},
            "critico_alto": {"min": 25, "max": 27},
        },
        "umidade": {
            "critico_baixo": {"min": 50, "max": 55},
            "alerta_baixo": {"min": 55, "max": 60},
            "ideal": {"min": 60, "max": 65},
            "alerta_alto": {"min": 65, "max": 70},
            "critico_alto": {"min": 70, "max": 75},
        },
        "luminosidade": {
            "critico_baixo": {"min": 15, "max": 17},
            "alerta_baixo": {"min": 17, "max": 20},
            "ideal": {"min": 20, "max": 23},
            "alerta_alto": {"min": 23, "max": 25},
            "critico_alto": {"min": 25, "max": 27},
        },
    },
]
def seed_presets(db: Session) -> None:
    # Como e chamado no boot principal da main, iteramos sobre aquele array gigante pre pronto em cima 
    # e checamos id a id. Se ele ja existe no postgresql, ele da skip pra nao comitar dados duplicados toda hr
    for preset in presets_cogumelos:
        existente = db.query(Preset).filter(Preset.id == preset["id"]).first()
        if not existente:
            db.add(Preset(**preset))
    db.commit()

def listar_presets(db: Session) -> list[Preset]:
    # Ao contrario das estufas onde o cara so lista os dados DELE usando o ID DO JWT... 
    # Aqui os presets do sistema sao publicos e compartilhados pra todo mundo que quer ver
    return db.query(Preset).all()

def buscar_preset_por_id(db: Session, id: str) -> Preset | None:
    return db.query(Preset).filter(Preset.id == id).first()

def buscar_preset_por_nome(db: Session, nome: str) -> Preset | None:
    return db.query(Preset).filter(Preset.nome_cultura == nome).first()

def vincular_preset_a_estufa(db: Session, estufa_id: str, preset_id: str) -> None:
    # Regra de negocio simples: Pega a estufa por id, levanta erro se nao tem e dps o preset por id
    # Como estufa ta ligada via SQL alchemy com foreign key, apenas atribuir ".preset_id" no row resolve a validacao
    estufa = db.query(Estufa).filter(Estufa.id == estufa_id).first()
    if not estufa:
        raise ValueError("Estufa nao encontrada")
        
    preset = db.query(Preset).filter(Preset.id == preset_id).first()
    if not preset:
        raise ValueError("Preset nao encontrado")
        
    estufa.preset_id = preset_id
    db.commit()