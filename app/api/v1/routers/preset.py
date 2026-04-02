from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.dependencies import get_current_user, get_db
from app.schemas.preset import PresetResposta
from app.services import preset_service

router = APIRouter(prefix="/api/presets", tags=["Presets"])

@router.get("/", response_model=list[PresetResposta])
async def listar_presets(
    db: Session = Depends(get_db),
):
    """Lista presets disponiveis para selecao de cultura."""
    return preset_service.listar_presets(db)

@router.get("/nome/{preset_nome}", response_model=PresetResposta)
async def buscar_preset_por_nome(
    preset_nome: str,
    db: Session = Depends(get_db),
):
    """Busca preset pelo nome de exibicao."""
    preset = preset_service.buscar_preset_por_nome(db, preset_nome)
    if not preset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset nao encontrado.")
    return preset

@router.get("/{preset_id}", response_model=PresetResposta)
async def buscar_preset(
    preset_id: str,
    db: Session = Depends(get_db),
):
    """Busca preset pelo identificador unico."""
    preset = preset_service.buscar_preset_por_id(db, preset_id)
    if not preset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset nao encontrado.")
    return preset

@router.put("/{preset_id}/vincular/{estufa_id}", response_model=dict)
async def vincular_preset(
    preset_id: str,
    estufa_id: str,
    db: Session = Depends(get_db),

    user: dict = Depends(get_current_user),
):
    """Vincula um preset existente a uma estufa do usuario autenticado."""
    try:
        _ = user
        preset_service.vincular_preset_a_estufa(db, estufa_id, preset_id)
        return {"message": "Preset vinculado com sucesso"}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc