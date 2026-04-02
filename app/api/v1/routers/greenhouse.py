from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.schemas.estufa import CriarEstufa, AtualizarEstufa, EstufaResposta
from app.services import estufa_service

router = APIRouter(prefix="/api/estufas", tags=["Estufas"])

@router.get("/", response_model=list[EstufaResposta])
async def listar_estufas(
    # Para validar no back a relacao do criador
    # JWT = Token da conexao. db_session = Inversao de controle abrindo o banco e fechando no fim da rota
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Acessamos user["id"] porque o Depends do get_current_user ja decodificou as propriedades
    return estufa_service.listar_estufas(db, user["id"])

# Reposta tem o padrao de http_201 por ser POST -> Criação de recurso novo no bd
@router.post("/", response_model=EstufaResposta, status_code=status.HTTP_201_CREATED)
async def criar_estufa(
    payload: CriarEstufa,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        # A estufa service vai receber do token JWT que "Joao = Id tal", dessa forma, Joao 
        # nao pode criar uma Estufa com o ID do Pedro, ja que nao e possivel falsificar JWT assinado
        return estufa_service.criar_estufa(db, user["id"], payload)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

@router.get("/{estufa_id}", response_model=EstufaResposta)
async def buscar_estufa(
    estufa_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return estufa_service.buscar_estufa(db, estufa_id, user["id"])
    except FileNotFoundError as exc:
        # Pq retornar 404 e nao 500 generico? 404 facilita e avisa pro front que aquela pesquisa no search bar falhou vindo do back
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        # Caso o cara mande request no insomnia do id da estufa do amiguinho
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

@router.put("/{estufa_id}", response_model=EstufaResposta)
async def atualizar_estufa(
    estufa_id: str,
    # O pydantic que vem daqui e o "AtualizarEstufa", ele e parcial entao todos os campos vao ser opcionais sem exceção
    payload: AtualizarEstufa,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
    try:
        return estufa_service.deletar_estufa(db, estufa_id, user["id"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
