"""Configuracoes da aplicacao carregadas a partir de variaveis de ambiente ou arquivo .env."""

from __future__ import annotations

import hashlib
import base64

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Parametros de ambiente para toda a aplicacao."""

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Plantelligence Backend"
    port: int = Field(default=4000, alias="PORT")
    frontend_origin: str = Field(default="http://localhost:5173", alias="FRONTEND_ORIGIN")

    jwt_secret: str = Field(default="change-me-in-production", alias="JWT_SECRET")
    jwt_refresh_secret: str = Field(default="change-refresh-secret", alias="JWT_REFRESH_SECRET")
    password_reset_secret: str = Field(default="change-password-reset-secret", alias="PASSWORD_RESET_SECRET")

    access_token_ttl_seconds: int = Field(default=900, alias="ACCESS_TOKEN_TTL_SECONDS")
    refresh_token_ttl_seconds: int = Field(default=604800, alias="REFRESH_TOKEN_TTL_SECONDS")
    password_reset_ttl_seconds: int = Field(default=900, alias="PASSWORD_RESET_TTL_SECONDS")
    password_expiry_days: int = Field(default=90, alias="PASSWORD_EXPIRY_DAYS")

    rate_limit_window_ms: int = Field(default=60000, alias="RATE_LIMIT_WINDOW_MS")
    rate_limit_max: int = Field(default=5, alias="RATE_LIMIT_MAX")

    database_url: str = Field(default="postgresql+psycopg2://postgres:postgres@localhost/plantelligence", alias="DB_URL")

    # InfluxDB (telemetria / series temporais)
    influx_url: str | None = Field(default=None, alias="INFLUX_URL")
    influx_token: str | None = Field(default=None, alias="INFLUX_TOKEN")
    influx_org: str | None = Field(default=None, alias="INFLUX_ORG")
    influx_bucket: str = Field(default="plantelligence", alias="INFLUX_BUCKET")

    smtp_host: str = Field(default="smtp.office365.com", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_secure: bool = Field(default=False, alias="SMTP_SECURE")
    smtp_user: str | None = Field(default=None, alias="SMTP_USER")
    smtp_password: str | None = Field(default=None, alias="SMTP_PASSWORD")
    smtp_from: str | None = Field(default=None, alias="SMTP_FROM")

    mfa_debug_mode: bool = Field(default=False, alias="MFA_DEBUG_MODE")
    mfa_issuer: str = Field(default="Plantelligence", alias="MFA_ISSUER")
    mfa_totp_secret_key: str | None = Field(default=None, alias="MFA_TOTP_SECRET_KEY")

    @property
    def cors_origins(self) -> list[str]:
        """Lista de origens permitidas para CORS."""

        values = [item.strip() for item in self.frontend_origin.split(",") if item.strip()]
        return values or ["*"]

    @property
    def resolved_smtp_from(self) -> str | None:
        """Remetente SMTP efetivo."""

        return self.smtp_from or self.smtp_user

    @property
    def totp_encryption_key(self) -> bytes:
        """Deriva chave de 32 bytes para criptografia do segredo TOTP."""

        direct = self.mfa_totp_secret_key
        if direct:
            try:
                decoded = base64.b64decode(direct)
                if len(decoded) == 32:
                    return decoded
            except Exception:
                pass

            if len(direct) >= 32:
                return hashlib.sha256(direct.encode("utf-8")).digest()

        return hashlib.sha256(self.jwt_secret.encode("utf-8")).digest()



settings = Settings()
