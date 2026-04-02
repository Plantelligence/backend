#!/bin/bash
# Startup v7 — Azure App Service (Python)
# Estrategia: .python_packages (CI build, GLIBC segura) > antenv (Oryx) > fallback
# Ordem invertida: antenv pode ter cryptography>=42 que exige GLIBC 2.33 (incompativel
# com o Azure App Service que roda GLIBC 2.31). O CI instala cryptography==41.0.7.

APP_DIR="/home/site/wwwroot"
cd "$APP_DIR"

echo "[startup] ============================================================"
echo "[startup] DIR   : $(pwd)"
echo "[startup] PORT  : ${PORT:-8000}"
echo "[startup] DATE  : $(date -u)"
echo "[startup] FILES : $(ls -1 | head -30)"
echo "[startup] ============================================================"

PYTHON=""

# ── 1. Pacotes pre-instalados no CI (.python_packages) — prioridade maxima ───
#    CI usa cryptography==41.0.7 (manylinux_2_17, GLIBC 2.17+) ✓
if [ -d "$APP_DIR/.python_packages/lib/site-packages" ]; then
    echo "[startup] Usando .python_packages (CI build — GLIBC compativel)"
    export PYTHONPATH="$APP_DIR/.python_packages/lib/site-packages${PYTHONPATH:+:$PYTHONPATH}"
    echo "[startup] PYTHONPATH=$PYTHONPATH"
    for py in python3.11 python3.12 python3.10 python3 python; do
        if command -v "$py" >/dev/null 2>&1; then
            PYTHON="$(command -v "$py")"
            break
        fi
    done
    [ -z "$PYTHON" ] && echo "[startup] ERRO: Python nao encontrado" >&2 && exit 1
    echo "[startup] Python  : $($PYTHON --version 2>&1)"

# ── 2. Virtualenv criado pelo Oryx (antenv) — fallback ───────────────────────
#    Pode ter cryptography incompativel; so usa se .python_packages nao existir
elif [ -f "$APP_DIR/antenv/bin/activate" ]; then
    echo "[startup] AVISO: usando antenv (Oryx) — pode ter incompatibilidade GLIBC"
    source "$APP_DIR/antenv/bin/activate"
    PYTHON="$(which python)"
    echo "[startup] Python  : $($PYTHON --version 2>&1)"

# ── 3. Nenhuma das anteriores — Python do sistema (apenas diagnostico) ────────
else
    echo "[startup] AVISO: nem .python_packages nem antenv encontrado!" >&2
    ls -la "$APP_DIR" >&2
    for py in python3.11 python3.12 python3.10 python3 python; do
        if command -v "$py" >/dev/null 2>&1; then
            PYTHON="$(command -v "$py")"
            echo "[startup] Fallback sistema: $($PYTHON --version 2>&1)"
            break
        fi
    done
    if [ -z "$PYTHON" ]; then
        echo "[startup] ERRO CRITICO: Python nao encontrado!" >&2
        exit 1
    fi
fi

# ── Testa importacao do app ───────────────────────────────────────────────────
echo "[startup] Testando importacao de app.main..."
"$PYTHON" - <<'PYCHECK' 2>&1
import sys
sys.path.insert(0, '/home/site/wwwroot')
try:
    import app.main
    print("[startup] app.main OK")
except Exception as exc:
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYCHECK

if [ $? -ne 0 ]; then
    echo "[startup] AVISO: importacao falhou — iniciando servidor de diagnostico..." >&2
    exec "$PYTHON" "$APP_DIR/diagnostic_server.py"
fi

# ── Inicia uvicorn ────────────────────────────────────────────────────────────
echo "[startup] Iniciando uvicorn na porta ${PORT:-8000}..."
exec "$PYTHON" -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --timeout-keep-alive 120 \
    --log-level info
