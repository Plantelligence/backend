from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.schemas.clima_externo import ClimaExternoResposta
from app.schemas.clima_resposta import ClimaResposta
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


@router.get("/{estufa_id}/previsao", response_model=ClimaResposta)
async def buscar_previsao_estufa(
    estufa_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Previsao do tempo de 5 dias com alertas climaticos para a estufa."""
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
            detail="A estufa precisa ter cidade e estado cadastrados para buscar previsao.",
        )

    try:
        return await weather_service.buscar_clima_estufa(cidade_estufa, estado_estufa, estufa_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Erro ao consultar previsao: {exc}") from exc


@router.get("/{estufa_id}/alertas")
async def buscar_alertas_climaticos(
    estufa_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retorna apenas os alertas climaticos ativos para a estufa."""
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
            detail="A estufa precisa ter cidade e estado cadastrados para buscar alertas.",
        )

    try:
        resposta = await weather_service.buscar_clima_estufa(cidade_estufa, estado_estufa, estufa_id)
        return {"alertas": [a.model_dump() for a in resposta.alertas], "total": len(resposta.alertas)}
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Erro ao consultar alertas: {exc}") from exc
