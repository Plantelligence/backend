"""
Motor central de notificacoes e alertas do Plantelligence.

Responsabilidades:
  1. Receber alertas dos detectores automaticos ou de acoes manuais
  2. Verificar preferencias do usuario (canais, tipos bloqueados, quiet hours)
  3. Aplicar cooldown para evitar spam (por tipo + estufa)
  4. Deduplicar alertas repetidos na mesma janela de tempo
  5. Criar notificacao in-app no banco de dados
  6. Enviar email quando o canal email estiver habilitado
  7. Registrar no log de auditoria

Fluxo de um alerta:
  Detector → dispatch() → verificar preferencias → verificar cooldown
    → criar notificacao in-app → enviar email (se habilitado)

Canais suportados:
  - in-app: notificacao salva no banco (tabela notifications)
  - email: email transacional via email_service

Nao usa WebSockets — o frontend consulta via polling REST.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.postgres.session import get_session
from app.models.notification import Notification
from app.models.notification_preference import NotificationPreference

logger = logging.getLogger(__name__)

# Cooldown por severidade (minutos) — evita spam do mesmo tipo na mesma estufa
_COOLDOWN_MINUTES = {
    "critical": 15,
    "warning": 30,
    "info": 60,
}

# Severidades que sempre furam quiet hours
_ALWAYS_DELIVER = {"critical"}


class NotificationEngine:
    """Motor de dispatch de notificacoes."""

    def dispatch(
        self,
        *,
        user_id: str,
        notification_type: str,
        severity: str,
        title: str,
        message: str,
        greenhouse_id: str | None = None,
        metadata: dict | None = None,
    ) -> Notification | None:
        """
        Despacha uma notificacao para um usuario especifico.

        Verifica preferencias, cooldown e quiet hours antes de criar.

        Retorna a Notification criada ou None se foi suprimida.
        """
        with get_session() as db:
            # verificar se o tipo esta bloqueado pelo usuario
            prefs = self._get_preferences(db, user_id)
            if prefs and notification_type in (prefs.blocked_types or []):
                logger.info(
                    "notification_blocked type=%s user_id=%s",
                    notification_type,
                    user_id,
                )
                return None

            # verificar quiet hours
            if not self._is_quiet_hours(prefs, severity):
                pass  # fora de quiet hours — prosseguir
            elif severity in _ALWAYS_DELIVER:
                pass  # critico sempre passa
            else:
                logger.info(
                    "notification_quiet_hours type=%s user_id=%s",
                    notification_type,
                    user_id,
                )
                return None

            # verificar cooldown
            if self._is_in_cooldown(db, user_id, notification_type, greenhouse_id, severity):
                logger.info(
                    "notification_cooldown type=%s user_id=%s greenhouse_id=%s",
                    notification_type,
                    user_id,
                    greenhouse_id,
                )
                return None

            # criar notificacao in-app
            now_iso = datetime.now(timezone.utc).isoformat()
            notification = Notification(
                user_id=user_id,
                notification_type=notification_type,
                severity=severity,
                title=title,
                message=message,
                greenhouse_id=greenhouse_id,
                metadata=metadata,
                read=False,
                read_at=None,
                dismissed_at=None,
            )
            db.add(notification)
            db.commit()
            db.refresh(notification)

            logger.info(
                "notification_created id=%s type=%s severity=%s user_id=%s",
                notification.id,
                notification_type,
                severity,
                user_id,
            )

            # enviar email se canal habilitado
            if prefs is None or prefs.channel_email:
                self._send_email(notification)

            return notification

    def dispatch_to_greenhouse_team(
        self,
        *,
        greenhouse_id: str,
        responsible_user_ids: list[str],
        notification_type: str,
        severity: str,
        title: str,
        message: str,
        metadata: dict | None = None,
    ) -> list[Notification]:
        """
        Despacha uma notificacao para todos os responsaveis de uma estufa.
        Usado para alertas de metricas, clima e dispositivos.
        """
        created: list[Notification] = []
        for user_id in responsible_user_ids:
            result = self.dispatch(
                user_id=user_id,
                notification_type=notification_type,
                severity=severity,
                title=title,
                message=message,
                greenhouse_id=greenhouse_id,
                metadata=metadata,
            )
            if result:
                created.append(result)
        return created

    # ── Helpers internos ──────────────────────────────────────────────────

    def _get_preferences(self, db, user_id: str) -> NotificationPreference | None:
        """Busca preferencias do usuario ou retorna None (padroes)."""
        return (
            db.query(NotificationPreference)
            .filter(NotificationPreference.user_id == user_id)
            .first()
        )

    def _is_quiet_hours(self, prefs: NotificationPreference | None, severity: str) -> bool:
        """Verifica se estamos dentro do horario de silencio."""
        if not prefs or not prefs.quiet_hours_start or not prefs.quiet_hours_end:
            return False

        now = datetime.now(timezone.utc)
        current_minutes = now.hour * 60 + now.minute

        start_parts = prefs.quiet_hours_start.split(":")
        end_parts = prefs.quiet_hours_end.split(":")
        start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
        end_minutes = int(end_parts[0]) * 60 + int(end_parts[1])

        if start_minutes <= end_minutes:
            in_range = start_minutes <= current_minutes <= end_minutes
        else:
            # cruza meia-noite (ex.: 22:00 → 07:00)
            in_range = current_minutes >= start_minutes or current_minutes <= end_minutes

        if not in_range:
            return False

        # dentro de quiet hours — verificar se severidade e suprimida
        if severity == "critical":
            return False
        if severity == "warning" and not prefs.quiet_hours_include_warning:
            return False

        return True

    def _is_in_cooldown(
        self,
        db,
        user_id: str,
        notification_type: str,
        greenhouse_id: str | None,
        severity: str,
    ) -> bool:
        """Verifica se existe notificacao recente do mesmo tipo na janela de cooldown."""
        cooldown_minutes = _COOLDOWN_MINUTES.get(severity, 30)
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)).isoformat()

        query = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.notification_type == notification_type,
                Notification.created_at >= cutoff,
            )
        )

        if greenhouse_id:
            query = query.filter(Notification.greenhouse_id == greenhouse_id)

        return query.first() is not None

    def _send_email(self, notification: Notification) -> None:
        """Envia email correspondente ao tipo de notificacao."""
        try:
            from app.services.email_service import send_notification_email
            send_notification_email(notification)
        except Exception as exc:
            logger.warning(
                "notification_email_failed id=%s error=%s",
                notification.id,
                exc,
            )


# ── Singleton ───────────────────────────────────────────────────────────────

_instance: NotificationEngine | None = None


def get_notification_engine() -> NotificationEngine:
    """Retorna a instancia unica do motor de notificacoes."""
    global _instance
    if _instance is None:
        _instance = NotificationEngine()
    return _instance
