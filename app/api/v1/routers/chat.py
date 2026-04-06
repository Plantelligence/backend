from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import chat_service
from app.core.dependencies import get_current_user
from app.core.rate_limit import limiter

router = APIRouter(prefix="/api/chat", tags=["Chat"])


class PresetSuggestionRequest(BaseModel):
    question: str = Field(..., min_length=5, max_length=1200)


class PresetSuggestionResponse(BaseModel):
    name: str
    summary: str
    temperature: dict
    humidity: dict
    soilMoisture: dict
    notes: list[str]

@router.post("/", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat(
    request: Request,
    payload: ChatRequest,
    user: dict = Depends(get_current_user),
):
    """Encaminha mensagens para o servico de IA e retorna a resposta."""
    _ = request
    _ = user
    try:
        resposta = await chat_service.send_message(payload.messages)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Assistente de IA indisponivel no momento. Tente novamente em instantes.",
        ) from exc

    return ChatResponse(response=resposta)


@router.post("/preset-suggestion", response_model=PresetSuggestionResponse)
@limiter.limit("10/minute")
async def suggest_preset(
    request: Request,
    payload: PresetSuggestionRequest,
    user: dict = Depends(get_current_user),
):
    """Sugere parametros de cultivo personalizados com apoio de IA."""
    _ = request
    _ = user
    try:
        suggestion = await chat_service.suggest_custom_profile(payload.question)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Assistente de IA indisponivel no momento. Tente novamente em instantes.",
        ) from exc

    return PresetSuggestionResponse(**suggestion)