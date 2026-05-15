"""
Serviço de chat com IA especializada em agricultura protegida (estufas).

Utiliza a API OpenRouter para acessar modelos de linguagem como o Qwen 3 32B.
O OpenRouter é compatível com a API da OpenAI, o que facilita a integração.

Fluxo de uma mensagem:
  1. O usuário digita uma pergunta sobre cultivo na estufa;
  2. O sistema verifica se a mensagem contém dados pessoais (LGPD);
  3. O sistema verifica se o tema está dentro do escopo de agricultura;
  4. Se aprovada, a mensagem é enviada à API com um prompt de sistema especializado;
  5. A resposta é retornada em formato markdown estruturado;
  6. Nenhum conteúdo das mensagens é armazenado — apenas métricas de uso.

Conformidade LGPD:
  - Dados pessoais (CPF, e-mail, telefone, endereço) são detectados e bloqueados;
  - O parâmetro ZDR (Zero Data Retention) força o OpenRouter a não reter prompts;
  - Apenas status, latência e modelo são registrados para observabilidade.

Controle de escopo:
  - Perguntas fora do contexto de agricultura/estufas são recusadas educadamente;
  - Tópicos bloqueados explicitamente: futebol, política, criptomoeda, programação, etc.

Variáveis de ambiente necessárias:
  OPENROUTER_API_KEY         — chave de acesso ao OpenRouter
  OPENROUTER_BASE_URL        — URL base da API (padrão: https://openrouter.ai/api/v1)
  OPENROUTER_MODEL_PRIMARY   — modelo principal (ex.: qwen/qwen3-32b)
  OPENROUTER_FALLBACK_MODELS — modelos de fallback separados por vírgula
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from time import perf_counter
from typing import Any

from openai import OpenAI

from app.config.settings import settings
from app.schemas.chat import ChatMessage

logger = logging.getLogger(__name__)

# ── Prompts do sistema ─────────────────────────────────────────────────────────
# O SYSTEM_PROMPT define o comportamento e as regras do assistente.
# É enviado em toda conversa, antes das mensagens do usuário.

SYSTEM_PROMPT = """
Voce e um assistente agricola especializado em estufas, sensores, atuadores,
microclima e cultivo.

REGRAS DE SEGURANCA E PRIVACIDADE:
- Nao solicite dados pessoais (nome, CPF, e-mail, telefone, endereco).
- Se o usuario enviar dados pessoais, peca para remover e reformular a pergunta.
- Responda de forma curta, objetiva e com passos praticos.
- Se nao souber, diga claramente que nao sabe e sugira medicoes/verificacoes.
- Se a pergunta estiver fora do contexto de estufas, sensores, atuadores, microclima e cultivo,
  recuse educadamente e informe que, por conformidade LGPD e politica do sistema,
  o assistente atende somente temas tecnicos de cultivo em estufa.

FORMATO OBRIGATORIO (sempre em markdown):
- Use exatamente estas secoes, nesta ordem:
    ### Diagnostico rapido
    ### O que fazer agora
    ### Erros comuns a evitar
    ### Quando pode ficar grave
- Em cada secao, use no maximo 3 bullets curtos.
- Se alguma secao nao se aplicar, escreva "Nao se aplica neste caso.".

REGRAS TECNICAS:
- Priorize orientacoes praticas para estufa e cultivo.
- Quando citar parametro, prefira faixa numerica (ex.: temperatura, umidade).
- Nunca invente dado de sensor; quando faltar contexto, diga o que medir.
""".strip()

# Mensagem de recusa para perguntas fora do escopo da plataforma
LGPD_REFUSAL_TEXT = (
    "Por conformidade LGPD e politica de seguranca da Plantelligence, "
    "eu so posso ajudar com temas tecnicos de cultivo em estufa "
    "(plantas, sensores, atuadores e microclima)."
)

# Mensagem de recusa quando dados pessoais são detectados na mensagem
PII_REFUSAL_TEXT = (
    "Detectei possiveis dados pessoais na mensagem. "
    "Por conformidade LGPD, remova dados como nome, CPF, e-mail, telefone ou endereco "
    "e reformule apenas com informacoes tecnicas de cultivo."
)

# ── Classificação de escopo ────────────────────────────────────────────────────
# Palavras-chave que indicam uma pergunta válida (dentro do escopo de agricultura)
AGRO_SCOPE_KEYWORDS = {
    "estufa", "cultivo", "planta", "plantas", "sensor", "sensores", "atuador", "atuadores",
    "microclima", "temperatura", "umidade", "luminosidade", "substrato", "irrigacao",
    "praga", "pragas", "fungo", "fungos", "cogumelo", "cogumelos", "solo", "ph",
    "vento", "ventilacao", "co2", "nutriente", "nutrientes", "doenca", "doencas",
    "fungicultura", "champignon", "shimeji", "shiitake", "portobello", "agaricus", "pleurotus", "lentinula",
}

# Palavras-chave que indicam tópicos explicitamente fora do escopo
BLOCKED_TOPIC_KEYWORDS = {
    "futebol", "politica", "eleicao", "criptomoeda", "bitcoin", "investimento",
    "programacao", "codigo", "filme", "serie", "musica", "fofoca", "celebridade",
    "jogo", "game", "aposta", "cassino", "loteria",
}

# ── Detecção de dados pessoais (PII) ──────────────────────────────────────────
# Expressões regulares para identificar CPF, e-mail e telefone brasileiro
PII_PATTERNS = (
    re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),  # CPF formatado (ex.: 123.456.789-00)
    re.compile(r"\b\d{11}\b"),                        # CPF sem pontuação (11 dígitos)
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),  # endereço de e-mail
    re.compile(r"\b(?:\+55\s?)?(?:\(?\d{2}\)?\s?)?9?\d{4}-?\d{4}\b"),  # telefone brasileiro
)

# ── Prompt para geração de perfil personalizado de cultivo ───────────────────
# Usado pela função suggest_custom_profile — retorna JSON estruturado
CUSTOM_PRESET_PROMPT = """
Voce e um agronomo especializado em fungicultura.
Retorne APENAS JSON valido (sem markdown) com este formato:
{
  "name": "nome curto do cultivo personalizado",
  "summary": "resumo curto do objetivo",
  "temperature": {"min": numero, "max": numero},
  "humidity": {"min": numero, "max": numero},
  "soilMoisture": {"min": numero, "max": numero},
  "notes": ["acao pratica 1", "acao pratica 2", "acao pratica 3"]
}
Use faixas realistas para cultivo de cogumelos.
""".strip()


class ChatService:
    """
    Serviço principal de chat com IA.

    Inicializado com as configurações do OpenRouter e mantém uma lista de modelos
    em ordem de preferência (primário + fallbacks). Se o modelo primário falhar,
    tenta automaticamente os fallbacks antes de retornar erro.
    """

    def __init__(self) -> None:
        self._api_key = (settings.openrouter_api_key or "").strip()
        self._base_url = (settings.openrouter_base_url or "https://openrouter.ai/api/v1").strip()
        self._primary_model = (settings.openrouter_model_primary or "meta-llama/llama-3.1-8b-instruct:free").strip()

        # monta a lista de modelos: primário primeiro, depois os fallbacks sem duplicatas
        fallbacks = [item.strip() for item in settings.openrouter_fallback_models if item.strip()]
        self._models = [self._primary_model]
        self._models.extend(model for model in fallbacks if model != self._primary_model)

        if not self._api_key:
            raise RuntimeError(
                "Assistente de IA indisponivel: OPENROUTER_API_KEY nao configurada."
            )

        self._client = OpenAI(base_url=self._base_url, api_key=self._api_key)

    @staticmethod
    def build_messages(history: list[ChatMessage]) -> list[dict[str, str]]:
        """
        Monta a lista de mensagens no formato da API OpenAI/OpenRouter.
        O prompt de sistema é sempre inserido no início, antes do histórico.
        """
        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in history:
            messages.append({"role": item.role.value, "content": item.content})
        return messages

    @staticmethod
    def _extract_latest_user_text(history: list[ChatMessage]) -> str:
        """Extrai o texto mais recente enviado pelo usuário para análise de conteúdo."""
        for item in reversed(history):
            if item.role.value == "user":
                return (item.content or "").strip()
        return ""

    @staticmethod
    def _contains_pii(text: str) -> bool:
        """
        Verifica se o texto contém dados pessoais identificáveis (PII).
        Detecta: CPF (com e sem pontuação), e-mail, telefone brasileiro,
        e palavras-chave como "cpf", "email", "telefone", "endereco".
        """
        if not text:
            return False
        lowered = _normalize_text(text)
        if any(token in lowered for token in ("cpf", "e-mail", "email", "telefone", "endereco")):
            return True

        # validação matemática do CPF para evitar falsos positivos com sequências de 11 dígitos
        cpf_candidates = _extract_cpf_candidates(text)
        if any(_is_valid_cpf(cpf) for cpf in cpf_candidates):
            return True

        # e-mail e telefone via regex (CPF já tratado com validação acima)
        return any(pattern.search(text) for pattern in PII_PATTERNS[2:])

    @staticmethod
    def _is_in_agro_scope(text: str) -> bool:
        """
        Verifica se a pergunta está dentro do escopo de agricultura/estufas.
        Retorna True se encontrar pelo menos uma palavra-chave agrícola.
        Retorna False se encontrar palavra-chave de tópico bloqueado.
        """
        if not text:
            return False
        lowered = _normalize_text(text)

        if any(keyword in lowered for keyword in AGRO_SCOPE_KEYWORDS):
            return True

        if any(keyword in lowered for keyword in BLOCKED_TOPIC_KEYWORDS):
            return False

        return False

    def _policy_gate(self, history: list[ChatMessage]) -> str | None:
        """
        Portão de políticas: verifica PII e escopo antes de chamar a API.
        Retorna uma mensagem de recusa se a política for violada, ou None se aprovado.
        Executa localmente sem custo de API.
        """
        user_text = self._extract_latest_user_text(history)
        if not user_text:
            return None

        if self._contains_pii(user_text):
            return PII_REFUSAL_TEXT

        if not self._is_in_agro_scope(user_text):
            return LGPD_REFUSAL_TEXT

        return None

    @staticmethod
    def _extract_provider_message(error_payload: Any) -> str:
        """Extrai a mensagem de erro do payload retornado pelo OpenRouter."""
        if isinstance(error_payload, dict):
            payload: dict[str, Any] = error_payload
            err = payload.get("error")
            if isinstance(err, dict):
                err_dict: dict[str, Any] = err
                message = err_dict.get("message")
                if isinstance(message, str):
                    return message.strip()

            top_message = payload.get("message")
            if isinstance(top_message, str):
                return top_message.strip()
        return ""

    @staticmethod
    def _extract_text_from_completion(response: Any) -> str:
        """
        Extrai o texto da resposta da API, compatível com diferentes modelos.
        Alguns modelos retornam o conteúdo em 'content', outros em 'reasoning'
        ou 'reasoning_details' (modelos de raciocínio encadeado).
        """
        if not getattr(response, "choices", None):
            return ""

        message = response.choices[0].message

        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()

        reasoning = getattr(message, "reasoning", None)
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning.strip()

        details = getattr(message, "reasoning_details", None)
        if isinstance(details, list):
            parts: list[str] = []
            for detail in details:
                if isinstance(detail, dict):
                    text = detail.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            if parts:
                return "\n".join(parts)

        return ""

    async def _call_with_fallbacks(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """
        Chama a API do OpenRouter tentando cada modelo da lista em ordem.
        Se o modelo primário falhar, tenta os fallbacks automaticamente.
        Registra latência e status de cada tentativa para observabilidade.
        Lança RuntimeError se todos os modelos falharem.
        """
        last_error: Exception | None = None

        for model in self._models:
            started_at = perf_counter()
            try:
                response = await asyncio.to_thread(
                    self._client.chat.completions.create,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_body={"provider": {"zdr": True}},  # ZDR = Zero Data Retention (LGPD)
                )
                elapsed_ms = int((perf_counter() - started_at) * 1000)
                logger.info(
                    "openrouter_chat_success model=%s latency_ms=%s",
                    model,
                    elapsed_ms,
                )

                content = self._extract_text_from_completion(response)
                if content:
                    return content

                raise RuntimeError("Assistente de IA indisponivel no momento. Tente novamente em instantes.")
            except Exception as exc:
                elapsed_ms = int((perf_counter() - started_at) * 1000)
                provider_message = self._extract_provider_message(getattr(exc, "body", None))
                status_code = getattr(exc, "status_code", None)

                logger.warning(
                    "openrouter_chat_error model=%s status=%s latency_ms=%s provider_message=%s",
                    model,
                    status_code,
                    elapsed_ms,
                    provider_message[:180],
                )
                last_error = exc
                continue

        # todos os modelos falharam — retorna mensagem amigável ao usuário
        if last_error is not None:
            status_code = getattr(last_error, "status_code", None)
            if status_code in (401, 403):
                raise RuntimeError("Assistente de IA indisponivel: credenciais invalidas ou sem permissao.")
            if status_code == 429:
                raise RuntimeError("Assistente de IA temporariamente indisponivel por limite de uso. Tente novamente.")

        raise RuntimeError("Assistente de IA indisponivel no momento. Tente novamente em instantes.")

    async def get_chat_reply(self, history: list[ChatMessage]) -> str:
        """
        Ponto de entrada principal: verifica políticas e retorna a resposta da IA.
        Se a mensagem violar alguma política, retorna a mensagem de recusa sem chamar a API.
        """
        refusal = self._policy_gate(history)
        if refusal:
            return refusal

        messages = self.build_messages(history)
        return await self._call_with_fallbacks(messages=messages, temperature=0.7, max_tokens=1024)

    async def suggest_custom_profile(self, question: str) -> dict[str, Any]:
        """
        Gera um perfil personalizado de cultivo usando IA.
        Recebe uma descrição de necessidade de cultivo e retorna parâmetros
        ideais de temperatura, umidade e umidade do solo em formato estruturado.
        Usado na criação de presets personalizados via IA no frontend.
        """
        messages = [
            {"role": "system", "content": CUSTOM_PRESET_PROMPT},
            {
                "role": "user",
                "content": (
                    "Com base nesta necessidade de cultivo, monte um perfil personalizado: "
                    f"{question}"
                ),
            },
        ]

        # temperature baixo (0.2) = resposta mais determinística e precisa para JSON
        text = await self._call_with_fallbacks(messages=messages, temperature=0.2, max_tokens=700)
        parsed = _extract_json_payload(text)

        return {
            "name": str(parsed.get("name") or "Personalizado IA"),
            "summary": str(parsed.get("summary") or "Perfil sugerido por IA."),
            "temperature": parsed.get("temperature") or {"min": 18, "max": 24},
            "humidity": parsed.get("humidity") or {"min": 80, "max": 90},
            "soilMoisture": parsed.get("soilMoisture") or {"min": 58, "max": 68},
            "notes": parsed.get("notes") if isinstance(parsed.get("notes"), list) else [],
            "raw": text,
        }


# ── Singleton do serviço ───────────────────────────────────────────────────────
# Instanciado sob demanda para que erros de configuração apareçam na primeira
# requisição, não no startup do servidor.

_chat_service_instance: ChatService | None = None


def _get_chat_service() -> ChatService:
    """Retorna a instância única do ChatService, criando-a se necessário."""
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService()
    return _chat_service_instance


# ── Funções auxiliares de parsing ─────────────────────────────────────────────

def _extract_json_payload(raw_text: str) -> dict[str, Any]:
    """
    Extrai o objeto JSON da resposta da IA.
    A IA às vezes envolve o JSON em blocos de código markdown (```json ... ```),
    então tenta o parse direto primeiro e depois busca por chaves {} no texto.
    """
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", raw_text)
    if not match:
        raise ValueError("Resposta da IA nao contem JSON valido.")

    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Formato de JSON invalido para perfil sugerido.")
    return parsed


# ── Funções públicas expostas para as rotas ───────────────────────────────────

async def send_message(messages: list[ChatMessage]) -> str:
    """Processa uma conversa e retorna a resposta da IA."""
    return await _get_chat_service().get_chat_reply(messages)


async def suggest_custom_profile(question: str) -> dict[str, Any]:
    """Gera um perfil de cultivo personalizado usando IA a partir de uma descrição."""
    return await _get_chat_service().suggest_custom_profile(question)


# ── Utilitários de texto ──────────────────────────────────────────────────────

def _normalize_text(value: str) -> str:
    """
    Remove acentos e converte para minúsculas para facilitar a comparação de palavras-chave.
    Exemplo: "Cogumelo" → "cogumelo", "umidade" → "umidade".
    """
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return without_accents.lower()


def _extract_cpf_candidates(value: str) -> list[str]:
    """
    Extrai sequências numéricas de 11 dígitos do texto como candidatos a CPF.
    Inclui CPFs formatados (XXX.XXX.XXX-XX) e sequências contínuas de dígitos.
    """
    numbers_only = re.sub(r"\D", "", value)
    candidates: list[str] = []

    for i in range(0, max(len(numbers_only) - 10, 0)):
        chunk = numbers_only[i:i + 11]
        if len(chunk) == 11:
            candidates.append(chunk)

    # CPFs no formato XXX.XXX.XXX-XX detectados como bônus
    formatted = re.findall(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", value)
    candidates.extend(re.sub(r"\D", "", item) for item in formatted)

    return list(dict.fromkeys(candidates))


def _is_valid_cpf(cpf: str) -> bool:
    """
    Valida matematicamente se uma sequência de 11 dígitos é um CPF real.
    Usa o algoritmo oficial de verificação dos dois dígitos verificadores.
    Rejeita sequências repetidas (111.111.111-11) que não são CPFs válidos.
    """
    if not cpf.isdigit() or len(cpf) != 11:
        return False
    if cpf == cpf[0] * 11:  # sequências como "00000000000" não são CPFs válidos
        return False

    def calc_digit(base: str, factor_start: int) -> int:
        total = 0
        factor = factor_start
        for char in base:
            total += int(char) * factor
            factor -= 1
        remainder = (total * 10) % 11
        return 0 if remainder == 10 else remainder

    first = calc_digit(cpf[:9], 10)
    second = calc_digit(cpf[:10], 11)
    return cpf[-2:] == f"{first}{second}"
