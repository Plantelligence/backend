from pydantic import BaseModel, Field
from enum import Enum

class MessageRole(str, Enum):
    # herda de str e de Enum: e necessario para o formato padrao do openai/groq 
    # onde eles esperam string, mas queremos validar so pro front mandar 'user' ou 'assistant'
    # para que nunca mandem um role nao existente 
    user = "user"
    assistant = "assistant"

class ChatMessage(BaseModel):
    # estrutura de cada mensagem enviada, onde o role e quem mandou e o content e o q foi dito
    role: MessageRole = Field(..., description="Role da mensagem")
    content: str = Field(..., description="Conteudo da mensagem")

class ChatRequest(BaseModel):
    # O chatbot padrao de llm nao tem memoria. Ele nao lembra da pergunta que vc fez de manha.
    # Para ele "lembrar" ele roda a api dele baseada num historico (array de mensagens) q o react manda inteiro 
    messages: list[ChatMessage] = Field(..., description="Lista de mensagens do chat")

class ChatResponse(BaseModel):
    # padrao de retorno da nossa api. Poderia retornar so uma string mas com 
    # basemodel a gente empacota num json limpo q o typescript pega direto (ex: data.response)
    response: str = Field(..., description="Resposta do chat")
