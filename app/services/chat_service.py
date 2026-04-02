import httpx
from app.config.settings import settings
from app.schemas.chat import ChatMessage, MessageRole

# Contexto global injetado em background. Esse e o molho secreto pq na real API pura da 
# groq ou do chatgpt e qnd vc so chama e n fala nada, ele assume que e p/ fofocar com vc normarmente.
# Dito isso a gente bate nela sempre falando: "ei amigao assume essa persona aqui rapidinho, vc vai falar de 
# fungos!". E isso salva nas contas do final os delirios da AI la da gringa de querer sugerir 
# receitas de prato de comida e afins ao longo das falanges geradas.

SYSTEM_PROMPT = """
Você é o PlantIA, um especialista em fungicultura e cultivo de cogumelos.
Sua missão é auxiliar cultivadores com dúvidas sobre cultivo, diagnósticos
de problemas e dicas práticas sobre fungicultura.

ESCOPO ESTRITO:
Responda EXCLUSIVAMENTE perguntas relacionadas a:
- Cultivo de cogumelos (shiitake, shimeji, portobello e outros)
- Diagnóstico de problemas: contaminações, pragas, doenças, crescimento anormal
- Condições ideais de cultivo: temperatura, umidade, substrato, iluminação
- Dicas e boas práticas de fungicultura
- Ciclo de vida dos fungos

Se a pergunta não for relacionada a fungicultura, responda educadamente que
você é especializado apenas em fungicultura e não pode ajudar com outros temas.
Não faça exceções mesmo que o usuário insista.

PERFIL DO USUÁRIO:
O usuário tem conhecimento básico a intermediário em fungicultura.
Use termos técnicos quando necessário, mas explique-os brevemente.
Não trate o usuário como completo leigo — seja direto e objetivo.

ESTRUTURA DA RESPOSTA:

Para dúvidas de cultivo:
- Resposta direta à pergunta
- Dica prática
- Erro comum a evitar (quando relevante)

Para diagnósticos de problemas:
- Causas mais prováveis (liste em ordem de probabilidade)
- O que verificar na sua estufa
- O que fazer agora
- Quando o problema pode ser mais grave

TOM DE VOZ:
- Profissional e direto, sem ser frio
- Nunca condescendente
- Respostas objetivas — evite enrolação
- Se precisar de mais detalhes para diagnosticar, peça antes de responder
"""

async def send_message(messages: list[ChatMessage]) -> str:
    # Prepara o JSON como um envelopao de chat do frontend. 
    # E isso pq o API groq la fora vai reescrever e simular os chats 
    # mas dnd isso ele precisa ler td que vcs falaram la em cima pra ele conseguir dar prosseguimento ao raciocinio.
    messages_payload = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    # Adiciona o histórico enviado pelo React
    for message in messages:
        messages_payload.append({
            "role": message.role.value,
            "content": message.content,
        })

    # Chama a API do Groq via httpx (async)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.groq_model,
                "messages": messages_payload,
                "temperature": 0.7,
                "max_tokens": 1024,
            },
            timeout=30.0,
        )

    # Lança exceção se o Groq retornar erro (4xx, 5xx)
    response.raise_for_status()

    data = response.json()
    return data["choices"][0]["message"]["content"]
