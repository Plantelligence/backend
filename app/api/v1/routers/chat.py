from fastapi import APIRouter, Depends
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import chat_service
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/chat", tags=["Chat"])

@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: dict = Depends(get_current_user),
):
    """Encaminha mensagens para o servico de IA e retorna a resposta."""
    _ = user
    resposta = await chat_service.send_message(request.messages)

    return ChatResponse(response=resposta)