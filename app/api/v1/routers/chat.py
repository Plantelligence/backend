from fastapi import APIRouter, Depends
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import chat_service
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/chat", tags=["Chat"])

@router.post("/", response_model=ChatResponse)
async def chat(
    # Diferente dos outros arquivos, esse chat n precia de id ou coisa mt custom na db do usuario. 
    # Sendo so o "request" com a lista do arr de messages dentro, ta otimo, mas mantemos o auth barrier tbm p ngm random fazer spam na gnt
    request: ChatRequest,
    user: dict = Depends(get_current_user),  
):
    # Await simples pro backend enviar o request assincrono ate o server do Llama Groq la fora
    resposta = await chat_service.send_message(request.messages)
    
    # Empacota em um response basico dict object 
    return ChatResponse(response=resposta)