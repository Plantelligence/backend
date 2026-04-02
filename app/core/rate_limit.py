"""Controle de taxa de requisicoes para proteger endpoints sensiveis contra abuso."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config.settings import settings

limiter = Limiter(key_func=get_remote_address, default_limits=[])
login_limit = f"{settings.rate_limit_max}/{max(settings.rate_limit_window_ms // 1000, 1)}seconds"
