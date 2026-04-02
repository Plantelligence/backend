"""Utilitarios para criptografar/decifrar segredos TOTP com AES-GCM."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config.settings import settings


def encrypt_secret(plaintext: str) -> dict[str, str]:
    """Criptografa um segredo em texto usando chave derivada do ambiente."""

    if not plaintext:
        raise ValueError("Secret encryption requires a non-empty string.")

    key = settings.totp_encryption_key
    aes = AESGCM(key)
    iv = os.urandom(12)
    ciphertext = aes.encrypt(iv, plaintext.encode("utf-8"), None)

    return {
        "iv": base64.b64encode(iv).decode("utf-8"),
        "data": base64.b64encode(ciphertext).decode("utf-8"),
    }


def decrypt_secret(payload: dict[str, str]) -> str:
    """Decifra payload de segredo criptografado."""

    if not payload or "iv" not in payload or "data" not in payload:
        raise ValueError("Secret payload missing required fields.")

    key = settings.totp_encryption_key
    aes = AESGCM(key)
    iv = base64.b64decode(payload["iv"])
    data = base64.b64decode(payload["data"])
    plaintext = aes.decrypt(iv, data, None)
    return plaintext.decode("utf-8")
