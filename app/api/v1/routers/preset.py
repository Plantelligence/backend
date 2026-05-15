from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel as PydanticBaseModel
from app.core.dependencies import get_current_user, get_db
from app.schemas.preset import CriarPresetUsuario, AtualizarPresetUsuario, PresetResposta
from app.services import preset_service

router = APIRouter(prefix="/api/presets", tags=["Presets"])


class SugestaoIAPayload(PydanticBaseModel):
    descricao: str


def _ensure_reader_read_only(user: dict) -> None:
    if (user.get("role") or "").strip() == "Reader":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Perfil Leitor possui acesso somente de consulta.")

@router.get("/", response_model=list[PresetResposta])
async def listar_presets(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lista presets disponiveis para selecao de cultura."""
    return preset_service.listar_presets(db, user["id"])


@router.post("/", response_model=PresetResposta, status_code=status.HTTP_201_CREATED)
async def criar_preset(
    payload: CriarPresetUsuario,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cria um preset personalizado para o usuario autenticado."""
    _ensure_reader_read_only(user)
    return preset_service.criar_preset_usuario(db, user["id"], payload)


@router.put("/{preset_id}", response_model=PresetResposta)
async def atualizar_preset(
    preset_id: str,
    payload: AtualizarPresetUsuario,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Atualiza um preset personalizado do usuario autenticado."""
    _ensure_reader_read_only(user)
    try:
        return preset_service.atualizar_preset_usuario(db, preset_id, user["id"], payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.delete("/{preset_id}", response_model=dict)
async def remover_preset(
    preset_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove um preset personalizado do usuario autenticado."""
    _ensure_reader_read_only(user)
    try:
        preset_service.remover_preset_usuario(db, preset_id, user["id"])
        return {"message": "Preset removido com sucesso", "presetId": preset_id}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

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


@router.post("/sugestao-ia")
async def sugerir_preset_com_ia(
    payload: SugestaoIAPayload,
    user: dict = Depends(get_current_user),
):
    # Solicita sugestão de parâmetros de cultivo via IA e retorna JSON estruturado.
    _ensure_reader_read_only(user)
    try:
        from app.services import chat_service
        sugestao = await chat_service.suggest_custom_profile(payload.descricao)
        return sugestao
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro ao gerar sugestão de perfil.") from exc