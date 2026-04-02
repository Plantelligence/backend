"""Aplicacao FastAPI principal do backend Plantelligence."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.routers import admin, auth, crypto, greenhouse, users
from app.config.settings import settings
from app.core.rate_limit import limiter
from app.services.security_logger import log_security_event

app = FastAPI(title=settings.app_name)
app.state.limiter = limiter


async def _init_db() -> None:
    """Cria tabelas no banco (roda em background, nao bloqueia o startup)."""
    try:
        from app.db.postgres.session import get_engine
        from app.db.postgres.Base import Base
        import app.models.user  # noqa: F401
        import app.models.greenhouse  # noqa: F401
        import app.models.token  # noqa: F401
        import app.models.mfa_challenge  # noqa: F401
        import app.models.login_session  # noqa: F401
        import app.models.registration_challenge  # noqa: F401
        import app.models.otp_enrollment  # noqa: F401
        import app.models.security_log  # noqa: F401

        real_engine = get_engine()
        await asyncio.to_thread(Base.metadata.create_all, real_engine)
        print("[startup] DB tables ensured.")
        await _migrate_schema(real_engine)
    except Exception as exc:
        print(f"[startup] DB init failed (nao critico): {exc}")


async def _migrate_schema(real_engine) -> None:
    """Adiciona novas colunas sem Alembic usando ALTER TABLE IF NOT EXISTS do PostgreSQL."""
    # Cada entrada e uma coluna nova adicionada em uma iteracao recente.
    # O IF NOT EXISTS garante idempotencia — rodar de novo nao causa erro.
    migrations = [
        "ALTER TABLE greenhouses ADD COLUMN IF NOT EXISTS sensors JSON",
        "ALTER TABLE greenhouses ADD COLUMN IF NOT EXISTS actuators JSON",
        "ALTER TABLE greenhouses ADD COLUMN IF NOT EXISTS parameters JSON",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions JSON",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS state VARCHAR",
        "ALTER TABLE registration_challenges ADD COLUMN IF NOT EXISTS city VARCHAR",
        "ALTER TABLE registration_challenges ADD COLUMN IF NOT EXISTS state VARCHAR",
    ]

    def _run() -> None:
        from sqlalchemy import text
        with real_engine.begin() as conn:
            for sql in migrations:
                conn.execute(text(sql))

    try:
        await asyncio.to_thread(_run)
        print("[startup] Schema migration OK.")
    except Exception as exc:
        print(f"[startup] Schema migration falhou (nao critico): {exc}")


@app.on_event("startup")
async def startup_event():
    """Dispara init do banco em background e retorna imediatamente."""
    smtp_ok = bool(settings.smtp_user and settings.smtp_password)
    print(f"[startup] SMTP configurado: {smtp_ok} | usuario: {'ok' if settings.smtp_user else 'AUSENTE'} | senha: {'ok' if settings.smtp_password else 'AUSENTE'}", flush=True)
    asyncio.create_task(_init_db())


# SlowAPI deve ficar dentro do CORS — assim TODAS as respostas
# (incluindo 429 de rate-limit) recebem os headers CORS corretamente.
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_error_message(detail) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    if isinstance(detail, list):
        return "Payload invalido para esta operacao."
    return str(detail)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    _ = exc
    return JSONResponse(
        status_code=429,
        content={"message": "Muitas tentativas de login. Tente novamente em instantes."},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    _ = request
    return JSONResponse(status_code=exc.status_code, content={"message": _resolve_error_message(exc.detail)})


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    _ = request
    _ = exc
    return JSONResponse(status_code=422, content={"message": "Payload invalido para esta operacao."})


@app.middleware("http")
async def security_log_http_errors(request: Request, call_next):
    response = await call_next(request)
    if response.status_code >= 400:
        async def _background_log() -> None:
            try:
                await asyncio.to_thread(
                    log_security_event,
                    action="http_error",
                    metadata={
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                    },
                    ip_address=request.client.host if request.client else None,
                )
            except Exception:
                pass

        asyncio.create_task(_background_log())
    return response


@app.get("/health")
async def health() -> dict:
    """Health check para Azure App Service."""
    return {"status": "ok"}


@app.get("/ping")
async def ping() -> dict:
    """Endpoint minimo de conectividade — sem autenticacao, sem DB."""
    return {"pong": True, "service": "plantelligence-api"}


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(admin.router)
app.include_router(crypto.router)
app.include_router(greenhouse.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    _ = request
    return JSONResponse(status_code=500, content={"message": f"Erro interno: {exc}"})
