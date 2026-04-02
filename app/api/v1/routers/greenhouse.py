from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.schemas.estufa import CriarEstufa, AtualizarEstufa, EstufaResposta
from app.services import greenhouse_service as estufa_service

router = APIRouter(prefix="/api/estufas", tags=["Estufas"])

@router.get("/", response_model=list[EstufaResposta])
async def listar_estufas(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lista as estufas do usuario autenticado."""
    return estufa_service.listar_estufas(db, user["id"])

@router.post("/", response_model=EstufaResposta, status_code=status.HTTP_201_CREATED)
async def criar_estufa(
    payload: CriarEstufa,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cria uma nova estufa para o usuario logado."""
    try:
        return estufa_service.criar_estufa(db, user["id"], payload)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

@router.get("/{estufa_id}", response_model=EstufaResposta)
async def buscar_estufa(
    estufa_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retorna uma estufa especifica quando o usuario tem acesso."""
    try:
        return estufa_service.buscar_estufa(db, estufa_id, user["id"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

@router.put("/{estufa_id}", response_model=EstufaResposta)
async def atualizar_estufa(
    estufa_id: str,
    payload: AtualizarEstufa,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Atualiza os dados de uma estufa existente."""
    try:
        return estufa_service.atualizar_estufa(db, estufa_id, user["id"], payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

@router.delete("/{estufa_id}", status_code=status.HTTP_200_OK)
async def deletar_estufa(
    estufa_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Exclui uma estufa do usuario autenticado."""
    try:
        return estufa_service.deletar_estufa(db, estufa_id, user["id"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
