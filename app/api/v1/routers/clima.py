from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.schemas.clima_resposta import ClimaResposta
from app.services import estufa_service, weather_service

router = APIRouter(prefix="/api/clima", tags=["Clima"])

@router.get("/{estufa_id}", response_model=ClimaResposta)
async def buscar_clima(
    estufa_id: str,
    # Sempre passando user authentication p/ o cara n sair olhando clima da estufa dos outros (mesmo q n faca sentido ele querer isso mas enfim - seguranca)
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        # Passo 1: Busca e valida ser o id auth do cara ta vinculado ao user_id da table da estufa no db
        estufa = estufa_service.buscar_estufa(db, estufa_id, user["id"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    # Passo 2: O clima agora busca com a localizacao vinculada a conta (usuario).
    cidade_usuario = user.get("cidade")
    estado_usuario = user.get("estado")
    if not cidade_usuario or not estado_usuario:
        raise HTTPException(
            # Unprocessable Entity pois a logica q mandaram ta correta mas "falta material de trabalho"
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Seu perfil precisa ter cidade e estado cadastrados para buscar a previsao do tempo. Atualize seu perfil.",
        )

    try:
        # Por fim atiramos um await la pra class service de previsao do cara q retorna uma pydantic formatada
        return await weather_service.buscar_clima_estufa(cidade_usuario, estado_usuario, estufa_id)
        
    except RuntimeError as exc:
        # O dev esqueceu de por a key no arquivo ".env"
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        # Nao listado no weather map global (escreveu nome da cidade torto por ex)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        # Se cair aqui e erro do servidor deles, ai damos o famoso Bad Gateway na lata do front end lidar
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Erro ao consultar previsao: {exc}") from exc
