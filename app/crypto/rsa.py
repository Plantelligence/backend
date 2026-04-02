"""Par de chaves RSA para troca segura de chave simetrica."""

from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_key = _private_key.public_key()


def get_public_key_pem() -> str:
    """Exporta chave publica em formato PEM."""

    return _public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def encrypt_key_with_rsa(key: bytes) -> bytes:
    """Criptografa chave simetrica com RSA OAEP SHA-256."""

    return _public_key.encrypt(
        key,
        padding.OAEP(mgf=padding.MGF1(algorithm=SHA256()), algorithm=SHA256(), label=None),
    )


def decrypt_key_with_rsa(encrypted_key: bytes) -> bytes:
    """Decifra chave simetrica com chave privada RSA."""

    return _private_key.decrypt(
        encrypted_key,
        padding.OAEP(mgf=padding.MGF1(algorithm=SHA256()), algorithm=SHA256(), label=None),
    )
