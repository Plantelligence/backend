from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.schemas.clima_externo import ClimaExternoResposta
from app.services import greenhouse_service as estufa_service, weather_service

router = APIRouter(prefix="/api/clima", tags=["Clima"])


@router.get("/{estufa_id}/externo", response_model=ClimaExternoResposta)
async def buscar_clima_externo_atual(
    estufa_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Clima externo atual para o dashboard da estufa."""
    try:
        estufa = estufa_service.buscar_estufa(db, estufa_id, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    cidade_estufa = estufa.get("cidade") if isinstance(estufa, dict) else None
    estado_estufa = estufa.get("estado") if isinstance(estufa, dict) else None
    if not cidade_estufa or not estado_estufa:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A estufa precisa ter cidade e estado cadastrados para buscar clima externo.",
        )

    try:
        return await weather_service.buscar_clima_externo_atual(cidade_estufa, estado_estufa)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Erro ao consultar clima externo: {exc}") from exc
