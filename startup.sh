#!/bin/bash

APP_DIR="/home/site/wwwroot"
cd "$APP_DIR"

echo "[startup] DIR  : $(pwd)"
echo "[startup] PORT : ${PORT:-8000}"
echo "[startup] DATE : $(date -u)"

# limpa qualquer PYTHONPATH injetado pelo Azure (pode apontar para .python_packages com bcrypt incompatível)
unset PYTHONPATH

PYTHON=""

if [ -f "$APP_DIR/antenv/bin/activate" ]; then
    echo "[startup] Usando antenv (Oryx)"
    source "$APP_DIR/antenv/bin/activate"
    PYTHON="$(which python)"
else
    echo "[startup] AVISO: antenv não encontrado" >&2
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
    echo "[startup] importação falhou — iniciando servidor de diagnóstico..." >&2
    exec "$PYTHON" "$APP_DIR/diagnostic_server.py"
fi

echo "[startup] Iniciando uvicorn na porta ${PORT:-8000}..."
exec "$PYTHON" -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --timeout-keep-alive 120 \
    --log-level info
