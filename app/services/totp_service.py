# TOTP para autenticação de dois fatores via app autenticador

from __future__ import annotations

import pyotp

from app.config.settings import settings
from app.utils.secret_storage import decrypt_secret, encrypt_secret


class TotpSetup(dict):
    pass


def create_totp_setup(email: str, issuer: str | None = None) -> TotpSetup:
    secret = pyotp.random_base32()
    issuer_value = issuer or settings.mfa_issuer
    totp = pyotp.TOTP(secret)

    return TotpSetup(
        secret=secret,
        issuer=issuer_value,
        accountName=email,
        uri=totp.provisioning_uri(name=email, issuer_name=issuer_value),
        encryptedSecret=encrypt_secret(secret),
    )


def recreate_totp_setup(email: str, stored: dict) -> TotpSetup | None:
    # recria o setup a partir do segredo já cifrado no banco
    encrypted = stored.get("encryptedSecret")
    if not encrypted:
        return None

    secret = decrypt_secret(encrypted)
    issuer_value = stored.get("issuer") or settings.mfa_issuer
    account_name = stored.get("accountName") or email
    totp = pyotp.TOTP(secret)

    return TotpSetup(
        secret=secret,
        issuer=issuer_value,
        accountName=account_name,
        uri=totp.provisioning_uri(name=account_name, issuer_name=issuer_value),
        encryptedSecret=encrypted,
    )


def verify_totp_code(token: str, secret: str) -> bool:
    # valid_window=1 tolera ±30s de defasagem de relógio
    return pyotp.TOTP(secret).verify(token.strip(), valid_window=1)


def verify_totp_code_with_encrypted_secret(token: str, encrypted_secret: dict) -> bool:
    secret = decrypt_secret(encrypted_secret)
    return verify_totp_code(token, secret)
