"""Criptografia AES-256-GCM para payloads de comunicacao segura."""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypt_with_aes(plaintext: str) -> dict:
    """Criptografa string UTF-8 gerando chave aleatoria de sessao."""

    key = os.urandom(32)
    iv = os.urandom(12)
    aes = AESGCM(key)
    ciphertext = aes.encrypt(iv, plaintext.encode("utf-8"), None)
    # Em AESGCM da biblioteca cryptography, os 16 bytes finais sao o auth tag.
    auth_tag = ciphertext[-16:]
    encrypted = ciphertext[:-16]

    return {
        "key": key,
        "iv": iv,
        "authTag": auth_tag,
        "ciphertext": encrypted,
    }


def decrypt_with_aes(payload: dict) -> str:
    """Decifra payload AES-256-GCM para texto."""

    aes = AESGCM(payload["key"])
    combined = payload["ciphertext"] + payload["authTag"]
    plaintext = aes.decrypt(payload["iv"], combined, None)
    return plaintext.decode("utf-8")
