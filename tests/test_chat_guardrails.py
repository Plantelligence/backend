"""Testes de guardrails para o chat (LGPD + escopo + resiliencia de parsing)."""

from __future__ import annotations

import unittest

from app.schemas.chat import ChatMessage, MessageRole
from app.services.chat_service import (
    ChatService,
    LGPD_REFUSAL_TEXT,
    PII_REFUSAL_TEXT,
    _is_valid_cpf,
)


class _FakeMessage:
    def __init__(self, content=None, reasoning=None, reasoning_details=None):
        self.content = content
        self.reasoning = reasoning
        self.reasoning_details = reasoning_details


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeResponse:
    def __init__(self, message):
        self.choices = [_FakeChoice(message)]


class ChatGuardrailsTestCase(unittest.TestCase):
    def test_validate_cpf_checksum(self):
        self.assertTrue(_is_valid_cpf("52998224725"))
        self.assertFalse(_is_valid_cpf("52998224724"))

    def test_policy_gate_blocks_pii(self):
        history = [
            ChatMessage(role=MessageRole.user, content="Meu cpf e 529.982.247-25, pode ajudar?")
        ]
        refusal = ChatService._policy_gate(ChatService.__new__(ChatService), history)
        self.assertEqual(refusal, PII_REFUSAL_TEXT)

    def test_policy_gate_blocks_out_of_scope(self):
        history = [
            ChatMessage(role=MessageRole.user, content="Quem ganhou o jogo ontem?")
        ]
        refusal = ChatService._policy_gate(ChatService.__new__(ChatService), history)
        self.assertEqual(refusal, LGPD_REFUSAL_TEXT)

    def test_policy_gate_allows_agro_question(self):
        history = [
            ChatMessage(role=MessageRole.user, content="Como ajustar temperatura da estufa para reduzir pragas?")
        ]
        refusal = ChatService._policy_gate(ChatService.__new__(ChatService), history)
        self.assertIsNone(refusal)

    def test_extract_text_from_completion_uses_reasoning_when_content_is_empty(self):
        response = _FakeResponse(_FakeMessage(content=None, reasoning="Texto util de reasoning"))
        text = ChatService._extract_text_from_completion(response)
        self.assertEqual(text, "Texto util de reasoning")


if __name__ == "__main__":
    unittest.main()
