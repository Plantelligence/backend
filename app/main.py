# backend principal do Plantelligence

from __future__ import annotations

import asyncio

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.routers import admin, auth, chat, clima, crypto, greenhouse, preset, site, users
from app.config.settings import settings
from app.core.rate_limit import limiter
from app.services import auth_service
from app.services.security_logger import log_security_event

app = FastAPI(title=settings.app_name)
app.state.limiter = limiter


async def _init_db() -> None:
    # roda em background para não segurar o startup
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
        # modelos legados em pt precisam ser importados para o mapper resolver os relacionamentos
        import app.models.estufa  # noqa: F401
        import app.models.dispositivo  # noqa: F401
        import app.models.alertas  # noqa: F401
        import app.models.historico  # noqa: F401
        import app.models.preset  # noqa: F401

        real_engine = get_engine()
        await asyncio.to_thread(Base.metadata.create_all, real_engine)
        await asyncio.to_thread(_seed_presets_safe)
        print("[startup] DB tables ensured.")
        if settings.run_startup_migrations:
            await _migrate_schema(real_engine)
        else:
            print("[startup] Schema migration skipped (RUN_STARTUP_MIGRATIONS=false).")
        removed = await asyncio.to_thread(auth_service.purge_expired_demo_organizations, True)
        if removed:
            print(f"[startup] Demo expirado removido. Usuarios excluidos: {removed}")
    except Exception as exc:
        print(f"[startup] DB init failed (nao critico): {exc}")


async def _migrate_schema(real_engine) -> None:
    # migrações manuais sem Alembic; IF NOT EXISTS garante idempotência
    migrations = [
        "ALTER TABLE estufas ADD COLUMN IF NOT EXISTS responsible_user_ids JSON",
        "ALTER TABLE estufas ADD COLUMN IF NOT EXISTS alerts_enabled BOOLEAN DEFAULT TRUE",
        "ALTER TABLE estufas ADD COLUMN IF NOT EXISTS last_alert_at VARCHAR",
        "ALTER TABLE estufas ADD COLUMN IF NOT EXISTS cep VARCHAR(8)",
        "ALTER TABLE greenhouses ADD COLUMN IF NOT EXISTS sensors JSON",
        "ALTER TABLE greenhouses ADD COLUMN IF NOT EXISTS actuators JSON",
        "ALTER TABLE greenhouses ADD COLUMN IF NOT EXISTS parameters JSON",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions JSON",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS state VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked_at VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked_reason VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS organization_name VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS organization_key VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS organization_owner_id VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_by_user_id VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS invitation_sent_at VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS invitation_accepted_at VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_demo_account BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS demo_expires_at VARCHAR",
        "ALTER TABLE registration_challenges ADD COLUMN IF NOT EXISTS city VARCHAR",
        "ALTER TABLE registration_challenges ADD COLUMN IF NOT EXISTS state VARCHAR",
        "ALTER TABLE registration_challenges ADD COLUMN IF NOT EXISTS organization_name VARCHAR",
        "ALTER TABLE registration_challenges ADD COLUMN IF NOT EXISTS organization_key VARCHAR",
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


def _seed_presets_safe() -> None:
    from app.db.postgres.session import get_session
    from app.services.preset_service import seed_presets

    with get_session() as db:
        seed_presets(db)


@app.on_event("startup")
async def startup_event():
    smtp_ok = bool(settings.smtp_user and settings.smtp_password)
    print(f"[startup] SMTP configurado: {smtp_ok} | usuario: {'ok' if settings.smtp_user else 'AUSENTE'} | senha: {'ok' if settings.smtp_password else 'AUSENTE'}", flush=True)
    asyncio.create_task(_init_db())


# SlowAPI precisa ficar dentro do CORS para que o 429 também traga os headers corretos
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
    return {"status": "ok"}


@app.get("/ping")
async def ping() -> dict:
    return {"pong": True, "service": "plantelligence-api"}


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(admin.router)
app.include_router(crypto.router)
app.include_router(greenhouse.router)
app.include_router(clima.router)
app.include_router(preset.router)
app.include_router(chat.router)
app.include_router(site.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    _ = request
    _ = exc
    return JSONResponse(status_code=500, content={"message": "Erro interno. Tente novamente em instantes."})
