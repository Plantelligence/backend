"""Configuracoes centrais do backend FastAPI.

Segredos (JWT, SMTP e chaves de 2FA) devem vir de variaveis de ambiente
via arquivo .env por seguranca e conformidade LGPD.
"""

from __future__ import annotations

import hashlib
import base64
from urllib.parse import urlparse

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
    port: int = Field(default=4001, alias="PORT")
    frontend_origin: str = Field(default="http://localhost:5173", alias="FRONTEND_ORIGIN")
    frontend_public_url: str | None = Field(default=None, alias="FRONTEND_PUBLIC_URL")

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
    run_startup_migrations: bool = Field(default=False, alias="RUN_STARTUP_MIGRATIONS")

    # InfluxDB (telemetria / series temporais)
    influx_url: str | None = Field(default=None, alias="INFLUX_URL")
    influx_token: str | None = Field(default=None, alias="INFLUX_TOKEN")
    influx_org: str | None = Field(default=None, alias="INFLUX_ORG")
    influx_bucket: str = Field(default="plantelligence", alias="INFLUX_BUCKET")

    # OpenWeatherMap (previsao do tempo)
    openweathermap_api_key: str | None = Field(default=None, alias="OPENWEATHERMAP_API_KEY")

    # IA (OpenRouter compativel com OpenAI Chat Completions)
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL")
    openrouter_model_primary: str = Field(
        default="meta-llama/llama-3.1-8b-instruct:free",
        alias="OPENROUTER_MODEL_PRIMARY",
    )
    openrouter_model_fallbacks: str = Field(
        default="qwen/qwen3-6b-instruct:free,deepseek/deepseek-chat:free",
        alias="OPENROUTER_MODEL_FALLBACKS",
    )

    smtp_host: str = Field(default="smtp.office365.com", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_secure: bool = Field(default=False, alias="SMTP_SECURE")
    smtp_user: str | None = Field(default=None, alias="SMTP_USER")
    smtp_password: str | None = Field(default=None, alias="SMTP_PASSWORD")
    smtp_from: str | None = Field(default=None, alias="SMTP_FROM")

    mfa_debug_mode: bool = Field(default=False, alias="MFA_DEBUG_MODE")
    mfa_issuer: str = Field(default="Plantelligence", alias="MFA_ISSUER")
    mfa_totp_secret_key: str | None = Field(default=None, alias="MFA_TOTP_SECRET_KEY")
    mfa_email_logo_url: str | None = Field(default=None, alias="MFA_EMAIL_LOGO_URL")

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
    def resolved_frontend_public_url(self) -> str:
        """URL base do frontend para montar links de convite/reset."""

        if self.frontend_public_url and self.frontend_public_url.strip():
            return self.frontend_public_url.strip().rstrip("/")

        origins = self.cors_origins
        if origins:
            # Em ambientes com multiplas origens (localhost + dominio real),
            # prioriza URL HTTPS publica para links enviados por e-mail.
            for origin in origins:
                try:
                    parsed = urlparse(origin)
                    host = (parsed.hostname or "").lower()
                    if parsed.scheme == "https" and host not in {"localhost", "127.0.0.1"}:
                        return origin.rstrip("/")
                except Exception:
                    continue
            return origins[0].rstrip("/")
        return "http://localhost:5173"

    @property
    def openrouter_fallback_models(self) -> list[str]:
        """Lista normalizada de modelos fallback para chamadas no OpenRouter."""

        items = [item.strip() for item in self.openrouter_model_fallbacks.split(",") if item.strip()]
        return items

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
