"""Teste local de conectividade com OpenRouter.

Uso:
    python scripts/test_openrouter.py
"""

from __future__ import annotations

import os
from pathlib import Path
import time

from openai import OpenAI
from dotenv import load_dotenv


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")

    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    base_url = (os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1").strip()
    model = (os.getenv("OPENROUTER_MODEL_PRIMARY") or "meta-llama/llama-3.1-8b-instruct:free").strip()

    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY nao configurada.")

    client = OpenAI(base_url=base_url, api_key=api_key)

    started_at = time.perf_counter()
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": "Explique o que e LPU em uma frase."},
        ],
        temperature=0.2,
        max_tokens=250,
        extra_body={"provider": {"zdr": True}},
    )
    latency_ms = int((time.perf_counter() - started_at) * 1000)

    reply = completion.choices[0].message.content if completion.choices else ""
    if not reply and completion.choices:
        reply = getattr(completion.choices[0].message, "reasoning", "") or ""
    print(f"STATUS=SUCCESS")
    print(f"MODEL={model}")
    print(f"LATENCY_MS={latency_ms}")
    print(f"REPLY={reply}")


if __name__ == "__main__":
    main()
