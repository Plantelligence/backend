from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.dependencies import get_current_user, get_db
from app.schemas.preset import PresetResposta
from app.services import preset_service

router = APIRouter(prefix="/api/presets", tags=["Presets"])

@router.get("/", response_model=list[PresetResposta])
# Note que nesta view diferente da criacao de estufa, nos n inserimos check de "user" no Depends()
# Por padrao os presets nativos do sistema sao viaveis na aba global de catalogo por todo usuario sem estar logado ate.
async def listar_presets(
    db: Session = Depends(get_db),
):
    return preset_service.listar_presets(db)

# Colocamos o "/nome/xxx" fixo pq caso contrario o fastapi vai achar que 
# string "Cultura" na vdd e p/ ser resolvido na query de {preset_id} que tbm acha ser tudo str
@router.get("/nome/{preset_nome}", response_model=PresetResposta)
async def buscar_preset_por_nome(
    preset_nome: str,
    db: Session = Depends(get_db),
):
    preset = preset_service.buscar_preset_por_nome(db, preset_nome)
    if not preset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset nao encontrado.")
    return preset

@router.get("/{preset_id}", response_model=PresetResposta)
async def buscar_preset(
    preset_id: str,
    db: Session = Depends(get_db),
):
    preset = preset_service.buscar_preset_por_id(db, preset_id)
    if not preset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset nao encontrado.")
    return preset

# Rota pra o usuario pegar uma estufa vazia que ele acabou de setar 
# e fazer um link da foreign key "preset_id" para usar no front e preencher a dash
@router.put("/{preset_id}/vincular/{estufa_id}", response_model=dict)
async def vincular_preset(
    preset_id: str,
    estufa_id: str,
    db: Session = Depends(get_db),
    
    # Aqui a validacao do token de uso restrito do sistema de criacao ja cobra que ngm roube estufa alheia pra vincular
    user: dict = Depends(get_current_user),
):
    try:
        preset_service.vincular_preset_a_estufa(db, estufa_id, preset_id)
        return {"message": "Preset vinculado com sucesso"}
    except ValueError as exc:
        # Levanta excecao para ambos, estufa ou preset id errado e repassa com 404 pro front formatar vermelhinho 
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc