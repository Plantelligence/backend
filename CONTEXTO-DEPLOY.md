# CONTEXTO DE DEPLOY — Plantelligence Backend

> Documento vivo. Atualizar sempre que houver mudança de infraestrutura, estratégia de deploy ou contrato de API.
> Última atualização: 2026-03-31 (sessão 3)

---

## Arquitetura geral

```
Frontend (React/Vite)                Backend (FastAPI/Python 3.11)
Azure Static Web Apps          →     Azure App Service (planti-api, B1, BrazilSouth)
https://www.plantelligence.cloud     https://planti-api-aghhf0a7b3hdfpbr.brazilsouth-01.azurewebsites.net
```

**Banco de dados:** Azure Database for PostgreSQL (Flexible Server)
**Banco de telemetria:** InfluxDB (Azure) — integração pendente
**CI/CD:** GitHub Actions (repositório `Plantelligence/backend`)

---

## Estratégia de deploy atual

### Por que não usamos Oryx build

O Oryx (sistema de build do Azure) fazia **build incremental** — comparava checksums
e não substituía arquivos Python que julgava "iguais", mesmo com conteúdo diferente.
Isso fez com que código antigo permanecesse em disco mesmo após múltiplos deploys.

### Estratégia atual: `.python_packages` + `SCM_DO_BUILD_DURING_DEPLOYMENT=false`

```
GitHub Actions Runner (Ubuntu)
  └─ pip install --target=".python_packages/lib/site-packages" -r requirements.txt
  └─ zip -r deploy.zip .   (inclui .python_packages/ e startup.sh)
  └─ az webapp deploy --type zip

Azure App Service
  └─ Extrai o zip diretamente para /home/site/wwwroot/
  └─ Executa: bash /home/site/wwwroot/startup.sh
```

**Por que não usamos venv pré-compilado no CI:**
O `antenv/bin/gunicorn` tem shebang com caminho absoluto do runner do GitHub
(`/opt/hostedtoolcache/Python/3.11.x/...`) que não existe no Azure → startup falha.

**Por que usamos `startup.sh` em vez de startup command direto:**
O App Setting `PYTHONPATH` não é garantidamente aplicado ao startup command no
contexto do Azure App Service Linux. O `startup.sh` exporta `PYTHONPATH` explicitamente.

### Arquivo `startup.sh` (v3 — uvicorn direto)

```bash
export PYTHONPATH="/home/site/wwwroot/.python_packages/lib/site-packages"
cd /home/site/wwwroot
# Localiza python3.11 → python3 → python
# Lista pacotes instalados (diagnóstico)
# Testa importação do app com traceback antes de iniciar servidor
exec $PYTHON -m uvicorn app.main:app \
    --host 0.0.0.0 --port "${PORT:-8000}" \
    --workers 1 --timeout-keep-alive 120 --log-level info
```

**Mudança em relação à v2:** substituímos `gunicorn + UvicornWorker` por `uvicorn` diretamente.
A cadeia gunicorn→UvicornWorker falha silenciosamente (sem log visível) se qualquer
dependência de C extension for incompatível. Uvicorn direto é mais simples e produz
logs claros de startup, incluindo traceback completo de erros de importação.

---

## App Settings do Azure (planti-api)

| Variável | Valor / Descrição |
|---|---|
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `false` — Oryx desabilitado |
| `DISABLE_COLLECTSTATIC` | `true` |
| `PYTHONPATH` | `/home/site/wwwroot/.python_packages/lib/site-packages` |
| `FRONTEND_ORIGIN` | `https://www.plantelligence.cloud,https://plantelligence.cloud` |
| `DB_URL` | `postgresql+psycopg2://user:pass@host/db` |
| `JWT_SECRET` | *(secret)* |
| `JWT_REFRESH_SECRET` | *(secret)* |
| `PASSWORD_RESET_SECRET` | *(secret)* |
| `SMTP_USER` | *(opcional — sem SMTP, MFA retorna `debugCode`)* |
| `SMTP_PASSWORD` | *(opcional)* |
| `MFA_DEBUG_MODE` | `false` em produção |

---

## Workflow GitHub Actions (`.github/workflows/azure-app-service.yml`)

```
1. actions/checkout@v4
2. actions/setup-python@v5  (Python 3.11)
3. pip install --target=".python_packages/lib/site-packages" -r requirements.txt
4. zip -r deploy.zip .  (exclui .git, __pycache__, *.pyc, .env)
5. azure/login@v2  (AZURE_CREDENTIALS secret)
6. az webapp config appsettings set  (SCM_DO_BUILD_DURING_DEPLOYMENT=false, PYTHONPATH)
7. az webapp config set  --startup-file "bash /home/site/wwwroot/startup.sh"
8. az webapp deploy --type zip --timeout 600
9. az webapp restart
```

**Tempo estimado:** ~10 min (pip install ~3–4 min + upload ~2 min + startup ~30 s)

---

## Stack tecnológica

### Backend
| Pacote | Versão | Uso |
|---|---|---|
| fastapi | 0.116.1 | Framework HTTP |
| uvicorn[standard] | 0.35.0 | ASGI server |
| gunicorn | 23.0.0 | Process manager |
| pydantic / pydantic-settings | 2.x | Validação / configuração |
| sqlalchemy | 2.0.41 | ORM PostgreSQL |
| psycopg2-binary | 2.9.10 | Driver PostgreSQL |
| alembic | 1.16.1 | Migrações de schema |
| passlib[bcrypt] | 1.7.4 | Hash de senha (com pré-hash SHA-256) |
| PyJWT | 2.10.1 | Tokens JWT |
| pyotp | 2.9.0 | TOTP/MFA |
| cryptography | 45.0.7 | Cifração do segredo TOTP |
| slowapi | 0.1.9 | Rate limiting |
| email-validator | 2.2.0 | Validação de e-mail |

### Banco de dados (PostgreSQL)
Modelos principais: `User`, `Greenhouse`, `LoginSession`, `OtpEnrollment`,
`RegistrationChallenge`, `Token`, `MfaChallenge`, `SecurityLog`

---

## Correções históricas importantes

### 1. Senha — bcrypt 72-byte limit (`app/core/security.py`)
**Problema:** `passlib` lança erro para senhas > 72 bytes.
**Solução:** Pré-hash SHA-256 antes de passar ao bcrypt. SHA-256 sempre gera
64 chars hex, dentro do limite.
```python
def _prehash_password(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()
```

### 2. SMTP não configurado → MFA travava (`app/services/mfa_service.py`)
**Problema:** `create_mfa_challenge` levantava `RuntimeError` quando SMTP ausente.
**Solução:** Sem SMTP, pula envio de e-mail e retorna `debugCode` na resposta.
Em produção com SMTP configurado, o `debugCode` não é exposto.

### 3. Firebase removido (`app/db/firestore.py` — deletado)
**Migração completa para PostgreSQL.** O arquivo `firestore.py` e o método
`resolve_firebase_credentials_json` em `settings.py` foram removidos.
`firebase_admin` não está mais em `requirements.txt`.

### 4. InfluxDB preparado (`app/db/influx/influx.py`)
Arquivo reescrito com import condicional (`influxdb_client_async`).
Campos de configuração adicionados em `settings.py`:
`INFLUX_URL`, `INFLUX_TOKEN`, `INFLUX_ORG`, `INFLUX_BUCKET`.
**Pendente:** adicionar `influxdb-client[async]` ao `requirements.txt` quando integrar.

### 5. Ordem dos middlewares CORS (`app/main.py`)
**Problema:** `SlowAPIMiddleware` estava na camada mais externa — respostas de
rate-limit (429) e erros de startup não tinham header `Access-Control-Allow-Origin`.
**Solução:**
```python
app.add_middleware(SlowAPIMiddleware)   # interna
app.add_middleware(CORSMiddleware, ...)  # externa — envolve tudo
```

### 6. Firebase em `admin.py` → ModuleNotFoundError no startup
**Problema:** O router de admin importava `firebase_admin` que não estava instalado.
**Solução:** Substituído por query SQLAlchemy com `func.count(User.id)`.

### 7. DB init não bloqueante (`app/main.py`)
**Problema:** `Base.metadata.create_all(engine)` na inicialização bloqueava o startup.
**Solução:** Movido para `asyncio.create_task(_init_db())` — retorna imediatamente.

### 8. Código de e-mail duplicado no registro (`app/services/auth_service.py`)
**Problema:** `register_user` gerava dois códigos distintos:
- Código A: criado localmente, hash armazenado em `RegistrationChallenge`
- Código B: criado por `create_mfa_challenge`, enviado por e-mail

Com SMTP configurado, o e-mail chegava com o código B mas o banco tinha o hash do
código A → `confirm_registration_email` sempre retornava "Código inválido".
**Solução:** Remover `create_mfa_challenge` de `register_user`. Enviar o e-mail
diretamente via `send_mfa_code_email(email, code, expires_at)` usando o mesmo `code`
já armazenado. `debugCode` retornado quando SMTP ausente ou `MFA_DEBUG_MODE=true`.

---

## Contratos Frontend ↔ Backend

### Formato de tokens (resposta de login/mfa/refresh)
```json
{
  "user": { "id", "email", "role", "fullName", "phone", "mfa", ... },
  "tokens": {
    "accessToken": "JWT",
    "accessExpiresAt": "ISO 8601",
    "accessJti": "uuid",
    "refreshToken": "JWT",
    "refreshExpiresAt": "ISO 8601",
    "refreshJti": "uuid"
  },
  "passwordExpired": false
}
```

### Fluxo de registro
```
POST /api/auth/register          → { challengeId, expiresAt, debugCode? }
POST /api/auth/register/confirm  → { nextStep:"otp", otpSetupId, secret, uri, issuer, accountName }
POST /api/auth/register/otp      → { message, user }
```

### Fluxo de login
```
POST /api/auth/login             → { mfaRequired:true, sessionId, methods, passwordExpired }
POST /api/auth/mfa/initiate      → { method, configured, challengeId?, debugCode?, accountName }
POST /api/auth/mfa/verify        → { user, tokens, passwordExpired }
```

### Change password — formato plano (frontend)
```json
{ "currentPassword": "...", "newPassword": "...", "mfaCode": "123456", "challengeId": "uuid-se-email" }
```
O backend converte internamente para o formato `verification` que o service espera.

### OTP confirm — aceita dois formatos
```json
{ "enrollmentId": "...", "otpCode": "123456" }  ← frontend
{ "enrollmentId": "...", "code": "123456" }      ← legado
```

### GET /users/logs
Admin → todos os logs. Usuário comum → apenas os próprios.

### POST /api/greenhouse/ — resposta
```json
{ "greenhouse": { ...criada }, "greenhouses": [ ...lista atualizada ] }
```

### Segurança — mfa.otp.secret NUNCA é enviado ao cliente
`sanitize_user()` usa `_sanitize_mfa()` que remove o segredo TOTP cifrado.
O cliente recebe apenas `configuredAt`, `issuer`, `accountName`.

---

## Pendências conhecidas

- [ ] Startup do App Service ainda em investigação (ver histórico de "Starting the site...")
  — aguardar conclusão do deploy com `startup.sh`
- [ ] Configurar SMTP nas App Settings para MFA por e-mail funcionar em produção
- [ ] Integrar InfluxDB (adicionar `influxdb-client[async]` ao requirements.txt)
- [ ] Rotacionar credenciais expostas durante sessão de debug (PostgreSQL password, SP secret)
- [ ] Configurar Alembic para migrações de schema controladas
- [ ] Testar fluxo completo de registro → login → MFA end-to-end no ambiente de produção

---

## Variáveis de ambiente necessárias (Azure App Settings)

Mínimo para funcionar sem SMTP (modo debug):
```
DB_URL=postgresql+psycopg2://...
JWT_SECRET=<min 32 chars aleatórios>
JWT_REFRESH_SECRET=<min 32 chars aleatórios>
PASSWORD_RESET_SECRET=<min 32 chars aleatórios>
FRONTEND_ORIGIN=https://www.plantelligence.cloud,https://plantelligence.cloud
MFA_DEBUG_MODE=true   ← retorna debugCode nas respostas de MFA
```

Para e-mail funcionar (MFA por e-mail):
```
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USER=noreply@plantelligence.cloud
SMTP_PASSWORD=...
MFA_DEBUG_MODE=false
```
