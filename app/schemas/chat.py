from pydantic import BaseModel, Field
from enum import Enum

class MessageRole(str, Enum):
    # Mantem validacao de papeis aceitos no payload.
    user = "user"
    assistant = "assistant"

class ChatMessage(BaseModel):
    # Unidade de mensagem enviada ao endpoint.
    role: MessageRole = Field(..., description="Role da mensagem")
    content: str = Field(..., description="Conteudo da mensagem")

class ChatRequest(BaseModel):
    # Historico completo da conversa.
    messages: list[ChatMessage] = Field(..., description="Lista de mensagens do chat")

class ChatResponse(BaseModel):
    # Estrutura padrao de resposta.
    response: str = Field(..., description="Resposta do chat")
