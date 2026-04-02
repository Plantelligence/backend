#!/usr/bin/env python3
"""Servidor de diagnostico — ativado pelo startup.sh quando app.main falha no import.

Usa apenas stdlib. Responde em GET /ping e GET /debug com info do ambiente Azure.
Remover apos corrigir o problema de startup.
"""

from __future__ import annotations

import http.server
import json
import os
import sys
import traceback

PORT = int(os.environ.get("PORT", 8000))

def _collect_diagnostics() -> dict:
    wwwroot = "/home/site/wwwroot"
    diag: dict = {
        "mode": "DIAGNOSTIC — app.main failed to import",
        "python_version": sys.version,
        "python_executable": sys.executable,
        "cwd": os.getcwd(),
        "pythonpath": os.environ.get("PYTHONPATH", "(not set)"),
        "path_env": os.environ.get("PATH", "(not set)"),
        "port": PORT,
        "antenv_exists": os.path.exists(f"{wwwroot}/antenv"),
        "python_packages_exists": os.path.exists(f"{wwwroot}/.python_packages"),
        "wwwroot_files": os.listdir(wwwroot) if os.path.exists(wwwroot) else [],
        "sys_path": sys.path,
    }

    sys.path.insert(0, wwwroot)

    for pkg in ["fastapi", "uvicorn", "sqlalchemy", "pydantic", "psycopg2", "cryptography", "jwt", "pyotp", "slowapi", "passlib"]:
        try:
            __import__(pkg)
            diag[f"import_{pkg}"] = "OK"
        except Exception as exc:
            diag[f"import_{pkg}"] = f"FAILED: {type(exc).__name__}: {exc}"

    try:
        import app.main  # noqa: F401
        diag["import_app_main"] = "OK"
    except Exception as exc:
        diag["import_app_main"] = f"FAILED: {type(exc).__name__}: {exc}"
        diag["import_app_main_traceback"] = traceback.format_exc()

    return diag


DIAG = _collect_diagnostics()
BODY = json.dumps(DIAG, indent=2, default=str).encode()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"[diag-server] {fmt % args}\n")


print(f"[diag] Servidor de diagnostico iniciado na porta {PORT}", flush=True)
print(f"[diag] Acesse: /ping ou /debug para ver informacoes do ambiente", flush=True)
httpd = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
httpd.serve_forever()
