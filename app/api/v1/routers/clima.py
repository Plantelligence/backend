from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.schemas.clima_resposta import ClimaResposta
from app.services import estufa_service, weather_service

router = APIRouter(prefix="/api/clima", tags=["Clima"])

@router.get("/{estufa_id}", response_model=ClimaResposta)
async def buscar_clima(
    estufa_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retorna previsao e alertas climaticos para uma estufa autorizada."""
    try:
        estufa = estufa_service.buscar_estufa(db, estufa_id, user["id"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    _ = estufa
    cidade_usuario = user.get("cidade")
    estado_usuario = user.get("estado")
    if not cidade_usuario or not estado_usuario:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Seu perfil precisa ter cidade e estado cadastrados para buscar a previsao do tempo. Atualize seu perfil.",
        )

    try:
        return await weather_service.buscar_clima_estufa(cidade_usuario, estado_usuario, estufa_id)

    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Erro ao consultar previsao: {exc}") from exc
