#!/bin/bash

APP_DIR="/home/site/wwwroot"
cd "$APP_DIR"

echo "[startup] DIR   : $(pwd)"
echo "[startup] PORT  : ${PORT:-8000}"
echo "[startup] DATE  : $(date -u)"

PYTHON=""

# 1. antenv do Oryx — prioridade máxima (instalado com a GLIBC correta do Azure)
if [ -f "$APP_DIR/antenv/bin/activate" ]; then
    echo "[startup] Usando antenv (Oryx)"
    source "$APP_DIR/antenv/bin/activate"
    PYTHON="$(which python)"

# 2. .python_packages — fallback legado (CI build)
elif [ -d "$APP_DIR/.python_packages/lib/site-packages" ]; then
    echo "[startup] Usando .python_packages (CI build)"
    export PYTHONPATH="$APP_DIR/.python_packages/lib/site-packages${PYTHONPATH:+:$PYTHONPATH}"
    for py in python3.11 python3.12 python3.10 python3 python; do
        if command -v "$py" >/dev/null 2>&1; then
            PYTHON="$(command -v "$py")"
            break
        fi
    done

# 3. Python do sistema
else
    echo "[startup] AVISO: nenhum env encontrado, usando Python do sistema" >&2
    for py in python3.11 python3.12 python3.10 python3 python; do
        if command -v "$py" >/dev/null 2>&1; then
            PYTHON="$(command -v "$py")"
            break
        fi
    done
fi

if [ -z "$PYTHON" ]; then
    echo "[startup] ERRO: Python não encontrado" >&2
    exit 1
fi

echo "[startup] Python: $($PYTHON --version 2>&1)"

# Testa importação do app
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
    echo "[startup] AVISO: importação falhou — iniciando servidor de diagnóstico..." >&2
    exec "$PYTHON" "$APP_DIR/diagnostic_server.py"
fi

echo "[startup] Iniciando uvicorn na porta ${PORT:-8000}..."
exec "$PYTHON" -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --timeout-keep-alive 120 \
    --log-level info
