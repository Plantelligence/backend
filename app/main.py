# ─────────────────────────────────────────────────────────────────────────────
# Ponto de entrada principal do backend Plantelligence.
#
# Este arquivo configura e inicia o servidor FastAPI, que é o framework web
# responsável por receber e responder às requisições HTTP do frontend.
#
# Responsabilidades deste arquivo:
#   1. Criar a aplicação FastAPI com título e middlewares;
#   2. No startup: criar tabelas no banco, rodar migrações, popular dados iniciais
#      e iniciar o consumidor de mensagens do Azure IoT Hub;
#   3. Configurar CORS (para que o frontend React possa chamar a API);
#   4. Registrar tratadores de erros padronizados (HTTP 422, 429, 500, etc.);
#   5. Registrar todas as rotas (auth, users, greenhouse, dispositivos, etc.).
#
# Para iniciar o servidor localmente:
#   uvicorn app.main:app --host 0.0.0.0 --port 4001
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.routers import admin, auth, chat, clima, crypto, dispositivos, greenhouse, preset, relatorios, site, telemetria, users
from app.config.settings import settings
from app.core.rate_limit import limiter
from app.services import auth_service
from app.services.security_logger import log_security_event

# instancia a aplicação FastAPI com o título definido nas configurações
app = FastAPI(title=settings.app_name)

# vincula o limitador de requisições (SlowAPI) à aplicação
app.state.limiter = limiter


async def _init_db() -> None:
    """
    Inicializa o banco de dados PostgreSQL no startup do servidor.
    Roda em background (asyncio.create_task) para não atrasar a resposta do /health.

    Ordem de execução (importante — não alterar):
      1. Cria as tabelas que ainda não existem (create_all é idempotente);
      2. Roda as migrações manuais (ALTER TABLE, CREATE TABLE IF NOT EXISTS);
      3. Popula os presets padrão se ainda não existirem;
      4. Remove organizações de demonstração expiradas.

    As etapas 2 e 3 são executadas nessa ordem porque as migrações podem criar
    colunas que os presets precisam — se a ordem fosse invertida, o seed falharia.
    """
    try:
        from app.db.postgres.session import get_engine
        from app.db.postgres.Base import Base
        # importa todos os modelos para que o SQLAlchemy conheça as tabelas
        import app.models.user  # noqa: F401
        import app.models.greenhouse  # noqa: F401
        import app.models.token  # noqa: F401
        import app.models.mfa_challenge  # noqa: F401
        import app.models.login_session  # noqa: F401
        import app.models.registration_challenge  # noqa: F401
        import app.models.otp_enrollment  # noqa: F401
        import app.models.security_log  # noqa: F401
        # modelos legados em português precisam ser importados para o ORM resolver relacionamentos
        import app.models.estufa  # noqa: F401
        import app.models.dispositivo  # noqa: F401
        import app.models.alertas  # noqa: F401
        import app.models.historico  # noqa: F401
        import app.models.preset  # noqa: F401
        import app.models.relatorio  # noqa: F401

        real_engine = get_engine()
        # cria as tabelas no banco se não existirem (seguro rodar múltiplas vezes)
        await asyncio.to_thread(Base.metadata.create_all, real_engine)

        # roda migrações de schema (ADD COLUMN IF NOT EXISTS) antes de qualquer acesso
        if settings.run_startup_migrations:
            await _migrate_schema(real_engine)
        else:
            print("[startup] Schema migration skipped (RUN_STARTUP_MIGRATIONS=false).")

        # popula presets padrão (ex.: Champignon, Shimeji) se ainda não existirem
        try:
            await asyncio.to_thread(_seed_presets_safe)
        except Exception as seed_exc:
            print(f"[startup] Seed presets falhou (nao critico): {seed_exc}")

        print("[startup] DB tables ensured.")

        # remove organizações de demonstração cujo prazo de expiração já passou
        removed = await asyncio.to_thread(auth_service.purge_expired_demo_organizations, True)
        if removed:
            print(f"[startup] Demo expirado removido. Usuarios excluidos: {removed}")
    except Exception as exc:
        print(f"[startup] DB init failed (nao critico): {exc}")


async def _migrate_schema(real_engine) -> None:
    """
    Executa migrações manuais de schema no PostgreSQL.

    Cada linha é um comando SQL seguro (IF NOT EXISTS / DEFAULT) que pode ser
    executado múltiplas vezes sem erro — isso garante idempotência mesmo que
    o servidor reinicie várias vezes.

    Esta abordagem substitui o Alembic para simplificar o deploy sem precisar
    de um processo separado de migração.
    """
    migrations = [
        # colunas adicionadas progressivamente à tabela de estufas legadas
        "ALTER TABLE estufas ADD COLUMN IF NOT EXISTS responsible_user_ids JSON",
        "ALTER TABLE estufas ADD COLUMN IF NOT EXISTS alerts_enabled BOOLEAN DEFAULT TRUE",
        "ALTER TABLE estufas ADD COLUMN IF NOT EXISTS last_alert_at VARCHAR",
        "ALTER TABLE estufas ADD COLUMN IF NOT EXISTS alert_thresholds JSON",
        # tabela de relatórios (criada separadamente pois não existe no create_all original)
        "CREATE TABLE IF NOT EXISTS relatorios (id VARCHAR PRIMARY KEY, estufa_id VARCHAR NOT NULL REFERENCES estufas(id) ON DELETE CASCADE, periodo_inicio VARCHAR NOT NULL, periodo_fim VARCHAR NOT NULL, avg_temperatura VARCHAR, avg_umidade VARCHAR, avg_substrato VARCHAR, resumo VARCHAR, criado_em VARCHAR NOT NULL, criado_por_id VARCHAR)",
        "ALTER TABLE estufas ADD COLUMN IF NOT EXISTS cep VARCHAR(8)",
        # colunas para sensores/atuadores no modelo de estufas em inglês (greenhouse)
        "ALTER TABLE greenhouses ADD COLUMN IF NOT EXISTS sensors JSON",
        "ALTER TABLE greenhouses ADD COLUMN IF NOT EXISTS actuators JSON",
        "ALTER TABLE greenhouses ADD COLUMN IF NOT EXISTS parameters JSON",
        # colunas de permissões e localização do usuário
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions JSON",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS state VARCHAR",
        # colunas de controle de acesso
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked_at VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked_reason VARCHAR",
        # colunas de organização e convite de membros
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS organization_name VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS organization_key VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS organization_owner_id VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_by_user_id VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS invitation_sent_at VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS invitation_accepted_at VARCHAR",
        # colunas de conta de demonstração
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_demo_account BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS demo_expires_at VARCHAR",
        # colunas adicionadas ao desafio de registro
        "ALTER TABLE registration_challenges ADD COLUMN IF NOT EXISTS city VARCHAR",
        "ALTER TABLE registration_challenges ADD COLUMN IF NOT EXISTS state VARCHAR",
        "ALTER TABLE registration_challenges ADD COLUMN IF NOT EXISTS organization_name VARCHAR",
        "ALTER TABLE registration_challenges ADD COLUMN IF NOT EXISTS organization_key VARCHAR",
        # umidade do solo nos presets
        "ALTER TABLE presets ADD COLUMN IF NOT EXISTS umidade_solo JSON",
        # colunas adicionadas aos relatórios
        "ALTER TABLE relatorios ADD COLUMN IF NOT EXISTS avg_umidade_solo VARCHAR",
        "ALTER TABLE relatorios ADD COLUMN IF NOT EXISTS avg_luminosidade VARCHAR",
        # credenciais IoT Hub na tabela de dispositivos
        "ALTER TABLE dispositivos ADD COLUMN IF NOT EXISTS iothub_device_id VARCHAR",
        "ALTER TABLE dispositivos ADD COLUMN IF NOT EXISTS iothub_primary_key VARCHAR",
        "ALTER TABLE dispositivos ADD COLUMN IF NOT EXISTS iothub_sas_token VARCHAR",
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
    """
    Popula os presets padrão de cultivo no banco de dados.
    Executado de forma síncrona em thread separada para não bloquear o event loop.
    """
    from app.db.postgres.session import get_session
    from app.services.preset_service import seed_presets

    with get_session() as db:
        seed_presets(db)


@app.on_event("startup")
async def startup_event():
    """
    Executado automaticamente quando o servidor FastAPI é iniciado.
    Verifica a configuração do SMTP e inicia as tarefas de background:
      - _init_db: garante que o banco de dados está pronto;
      - _start_iothub_consumer: inicia a escuta de mensagens dos sensores IoT.
    """
    smtp_ok = bool(settings.smtp_user and settings.smtp_password)
    print(f"[startup] SMTP configurado: {smtp_ok} | usuario: {'ok' if settings.smtp_user else 'AUSENTE'} | senha: {'ok' if settings.smtp_password else 'AUSENTE'}", flush=True)
    asyncio.create_task(_init_db())
    asyncio.create_task(_start_iothub_consumer())


async def _start_iothub_consumer() -> None:
    """
    Inicia o consumidor de mensagens do Azure IoT Hub em background.
    Se a biblioteca azure-eventhub não estiver instalada ou as variáveis de ambiente
    não estiverem configuradas, o erro é registrado mas não interrompe o servidor.
    """
    try:
        from app.services.iothub_consumer import start_iothub_consumer
        start_iothub_consumer()
        print("[startup] IoT Hub consumer iniciado.", flush=True)
    except Exception as exc:
        print(f"[startup] IoT Hub consumer nao iniciado (nao critico): {exc}", flush=True)


@app.on_event("shutdown")
async def shutdown_event():
    """
    Executado quando o servidor é encerrado (CTRL+C ou sinal de término).
    Fecha a conexão com o InfluxDB de forma limpa para evitar conexões pendentes.
    """
    try:
        from app.db.influx.influx import influx_db
        await influx_db.close()
    except Exception:
        pass


# ── Middlewares ───────────────────────────────────────────────────────────────
# Ordem importa: SlowAPI (rate limit) deve ficar dentro do CORS para que
# respostas 429 também recebam os headers de CORS necessários para o browser.

app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,   # domínios permitidos (configurado no .env)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Tratadores de erros padronizados ─────────────────────────────────────────
# Todos os erros retornam JSON com o campo "message" para facilitar a exibição
# de mensagens amigáveis no frontend sem precisar tratar formatos diferentes.

def _resolve_error_message(detail) -> str:
    """Normaliza o campo detail do HTTPException para uma string legível."""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    if isinstance(detail, list):
        return "Payload invalido para esta operacao."
    return str(detail)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Retorna HTTP 429 quando o usuário excede o limite de requisições.
    Configurado principalmente para proteger a rota de login contra ataques de força bruta.
    """
    _ = exc
    return JSONResponse(
        status_code=429,
        content={"message": "Muitas tentativas de login. Tente novamente em instantes."},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Converte qualquer HTTPException em JSON padronizado com o campo 'message'."""
    _ = request
    return JSONResponse(status_code=exc.status_code, content={"message": _resolve_error_message(exc.detail)})


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Retorna HTTP 422 quando o payload da requisição não corresponde ao schema esperado.
    Mensagem genérica para não expor detalhes internos do schema ao cliente.
    """
    return JSONResponse(status_code=422, content={"message": "Payload invalido para esta operacao."})


@app.middleware("http")
async def security_log_http_errors(request: Request, call_next):
    """
    Middleware que registra automaticamente todos os erros HTTP (status >= 400)
    no log de segurança, incluindo método, caminho e IP do cliente.
    O registro é feito em background para não adicionar latência às respostas.
    """
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


# ── Rotas de saúde ────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    """Verifica se o servidor está respondendo. Usado pelo load balancer e monitoramento."""
    return {"status": "ok"}


@app.get("/ping")
async def ping() -> dict:
    """Confirmação rápida de que o serviço Plantelligence está ativo."""
    return {"pong": True, "service": "plantelligence-api"}


# ── Registro de rotas ─────────────────────────────────────────────────────────
# Cada módulo de router define seus próprios endpoints com prefixo /api/...

app.include_router(auth.router)          # autenticação: login, registro, MFA, WebAuthn
app.include_router(users.router)         # gerenciamento de usuários e organização
app.include_router(admin.router)         # painel administrativo
app.include_router(crypto.router)        # criptografia de dados sensíveis
app.include_router(greenhouse.router)    # estufas (modelo novo em inglês)
app.include_router(dispositivos.router)  # dispositivos IoT vinculados às estufas
app.include_router(relatorios.router)    # relatórios periódicos de desempenho
app.include_router(telemetria.router)    # recepção direta de leituras de sensores
app.include_router(clima.router)         # dados climáticos externos (CEP/cidade)
app.include_router(preset.router)        # perfis de cultivo pré-configurados
app.include_router(chat.router)          # assistente de IA para consultoria agrícola
app.include_router(site.router)          # rotas públicas do site institucional


# ── Tratador de erros não esperados ──────────────────────────────────────────
# Captura qualquer exceção que não foi tratada pelos handlers anteriores.
# Retorna HTTP 500 com mensagem genérica para não expor detalhes internos.

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Captura exceções inesperadas e retorna 500 com mensagem amigável."""
    _ = request
    _ = exc
    return JSONResponse(status_code=500, content={"message": "Erro interno. Tente novamente em instantes."})
