"""
Chat via OpenRouter (API compatível com OpenAI).

LGPD: ZDR forçado por requisição; sem registro de prompts ou respostas.
Só logamos status, latência e modelo para observabilidade.
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

LGPD_REFUSAL_TEXT = (
    "Por conformidade LGPD e politica de seguranca da Plantelligence, "
    "eu so posso ajudar com temas tecnicos de cultivo em estufa "
    "(plantas, sensores, atuadores e microclima)."
)

PII_REFUSAL_TEXT = (
    "Detectei possiveis dados pessoais na mensagem. "
    "Por conformidade LGPD, remova dados como nome, CPF, e-mail, telefone ou endereco "
    "e reformule apenas com informacoes tecnicas de cultivo."
)

AGRO_SCOPE_KEYWORDS = {
    "estufa", "cultivo", "planta", "plantas", "sensor", "sensores", "atuador", "atuadores",
    "microclima", "temperatura", "umidade", "luminosidade", "substrato", "irrigacao",
    "praga", "pragas", "fungo", "fungos", "cogumelo", "cogumelos", "solo", "ph",
    "vento", "ventilacao", "co2", "nutriente", "nutrientes", "doenca", "doencas",
    "fungicultura", "champignon", "shimeji", "shiitake", "portobello", "agaricus", "pleurotus", "lentinula",
}

BLOCKED_TOPIC_KEYWORDS = {
    "futebol", "politica", "eleicao", "criptomoeda", "bitcoin", "investimento",
    "programacao", "codigo", "filme", "serie", "musica", "fofoca", "celebridade",
    "jogo", "game", "aposta", "cassino", "loteria",
}

PII_PATTERNS = (
    re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),  # CPF formatado
    re.compile(r"\b\d{11}\b"),  # CPF sem pontuacao
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),  # Email
    re.compile(r"\b(?:\+55\s?)?(?:\(?\d{2}\)?\s?)?9?\d{4}-?\d{4}\b"),  # Telefone BR
)

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
    def __init__(self) -> None:
        self._api_key = (settings.openrouter_api_key or "").strip()
        self._base_url = (settings.openrouter_base_url or "https://openrouter.ai/api/v1").strip()
        self._primary_model = (settings.openrouter_model_primary or "meta-llama/llama-3.1-8b-instruct:free").strip()

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
        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in history:
            messages.append({"role": item.role.value, "content": item.content})
        return messages

    @staticmethod
    def _extract_latest_user_text(history: list[ChatMessage]) -> str:
        for item in reversed(history):
            if item.role.value == "user":
                return (item.content or "").strip()
        return ""

    @staticmethod
    def _contains_pii(text: str) -> bool:
        if not text:
            return False
        lowered = _normalize_text(text)
        if any(token in lowered for token in ("cpf", "e-mail", "email", "telefone", "endereco")):
            return True

        cpf_candidates = _extract_cpf_candidates(text)
        if any(_is_valid_cpf(cpf) for cpf in cpf_candidates):
            return True

        # e-mail e telefone ainda via regex (CPF já foi tratado acima)
        return any(pattern.search(text) for pattern in PII_PATTERNS[2:])

    @staticmethod
    def _is_in_agro_scope(text: str) -> bool:
        if not text:
            return False
        lowered = _normalize_text(text)

        if any(keyword in lowered for keyword in AGRO_SCOPE_KEYWORDS):
            return True

        # tópico bloqueado explicitamente tem precedência
        if any(keyword in lowered for keyword in BLOCKED_TOPIC_KEYWORDS):
            return False

        return False

    def _policy_gate(self, history: list[ChatMessage]) -> str | None:
        # guardrails locais antes de bater na API
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
        # diferentes modelos retornam content, reasoning ou reasoning_details
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
                    extra_body={"provider": {"zdr": True}},
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

        if last_error is not None:
            status_code = getattr(last_error, "status_code", None)
            if status_code in (401, 403):
                raise RuntimeError("Assistente de IA indisponivel: credenciais invalidas ou sem permissao.")
            if status_code == 429:
                raise RuntimeError("Assistente de IA temporariamente indisponivel por limite de uso. Tente novamente.")

        raise RuntimeError("Assistente de IA indisponivel no momento. Tente novamente em instantes.")

    async def get_chat_reply(self, history: list[ChatMessage]) -> str:
        refusal = self._policy_gate(history)
        if refusal:
            return refusal

        messages = self.build_messages(history)
        return await self._call_with_fallbacks(messages=messages, temperature=0.7, max_tokens=1024)

    async def suggest_custom_profile(self, question: str) -> dict[str, Any]:
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


_chat_service_instance: ChatService | None = None


def _get_chat_service() -> ChatService:
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService()
    return _chat_service_instance


def _extract_json_payload(raw_text: str) -> dict[str, Any]:
    # a IA às vezes embala o JSON em markdown; tenta parse direto primeiro
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


async def send_message(messages: list[ChatMessage]) -> str:
    return await _get_chat_service().get_chat_reply(messages)


async def suggest_custom_profile(question: str) -> dict[str, Any]:
    return await _get_chat_service().suggest_custom_profile(question)


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return without_accents.lower()


def _extract_cpf_candidates(value: str) -> list[str]:
    numbers_only = re.sub(r"\D", "", value)
    candidates: list[str] = []

    for i in range(0, max(len(numbers_only) - 10, 0)):
        chunk = numbers_only[i:i + 11]
        if len(chunk) == 11:
            candidates.append(chunk)

    # CPF formatado como bônus de detecção
    formatted = re.findall(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", value)
    candidates.extend(re.sub(r"\D", "", item) for item in formatted)

    return list(dict.fromkeys(candidates))


def _is_valid_cpf(cpf: str) -> bool:
    if not cpf.isdigit() or len(cpf) != 11:
        return False
    if cpf == cpf[0] * 11:
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
