"""Servico de simulacao de mensagem segura (RSA + AES)."""

from __future__ import annotations

import base64

from app.crypto.aes import decrypt_with_aes, encrypt_with_aes
from app.crypto.rsa import decrypt_key_with_rsa, encrypt_key_with_rsa, get_public_key_pem


def get_communication_public_key() -> str:
    """Retorna chave publica para clientes autenticados."""

    return get_public_key_pem()


def simulate_secure_message(message: str) -> dict:
    """Criptografa mensagem com AES e protege chave com RSA."""

    encrypted = encrypt_with_aes(message)
    encrypted_key = encrypt_key_with_rsa(encrypted["key"])

    return {
        "encryptedMessage": base64.b64encode(encrypted["ciphertext"]).decode("utf-8"),
        "encryptedKey": base64.b64encode(encrypted_key).decode("utf-8"),
        "iv": base64.b64encode(encrypted["iv"]).decode("utf-8"),
        "authTag": base64.b64encode(encrypted["authTag"]).decode("utf-8"),
    }


def verify_secure_message(payload: dict) -> str:
    """Valida se o payload criptografado pode ser decifrado corretamente."""

    decrypted_key = decrypt_key_with_rsa(base64.b64decode(payload["encryptedKey"]))
    return decrypt_with_aes(
        {
            "key": decrypted_key,
            "iv": base64.b64decode(payload["iv"]),
            "authTag": base64.b64decode(payload["authTag"]),
            "ciphertext": base64.b64decode(payload["encryptedMessage"]),
        }
    )
