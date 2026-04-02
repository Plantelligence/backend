"""Envio de e-mails transacionais: codigos MFA e alertas operacionais das estufas."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.config.settings import settings


def _smtp_send(message: EmailMessage) -> None:
    """Abre conexao SMTP e envia a mensagem, ativando STARTTLS quando necessario."""

    if not settings.smtp_user or not settings.smtp_password or not settings.resolved_smtp_from:
        raise RuntimeError("SMTP nao configurado. Defina SMTP_USER, SMTP_PASSWORD e SMTP_FROM.")

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=8) as server:
            if not settings.smtp_secure:
                server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(f"SMTP auth falhou ({exc.smtp_code}): {exc.smtp_error}") from exc
    except smtplib.SMTPConnectError as exc:
        raise RuntimeError(f"SMTP conexao falhou: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"SMTP erro ({type(exc).__name__}): {exc}") from exc


def send_mfa_code_email(to: str, code: str, expires_at: str) -> None:
    """Envia o codigo de verificacao MFA para o e-mail do usuario."""

    msg = EmailMessage()
    msg["From"] = settings.resolved_smtp_from
    msg["To"] = to
    msg["Subject"] = "Plantelligence - Codigo de autenticacao multifator"
    msg.set_content(
        f"Seu codigo MFA e {code}.\nEle expira em {expires_at}.\n"
        "Se voce nao solicitou este acesso, entre em contato com o suporte."
    )
    _smtp_send(msg)


def send_greenhouse_alert_email(
    recipients: list[str],
    greenhouse_name: str,
    profile: dict,
    metrics: dict,
    metrics_evaluation: dict,
    alerts: list[str],
) -> None:
    """Notifica a equipe responsavel quando os parametros da estufa saem da faixa ideal."""

    if not recipients:
        return

    msg = EmailMessage()
    msg["From"] = settings.resolved_smtp_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = f"Plantelligence - Alerta critico na estufa {greenhouse_name}"

    temperature = metrics.get("temperature", "n/d")
    humidity = metrics.get("humidity", "n/d")
    soil = metrics.get("soilMoisture", "n/d")
    alerts_text = "\n".join(f"- {item}" for item in alerts)

    msg.set_content(
        "Equipe Plantelligence,\n\n"
        f"Detectamos desvios na estufa '{greenhouse_name}' ({profile.get('name')}).\n\n"
        f"Resumo:\n{alerts_text}\n\n"
        "Leituras atuais:\n"
        f"- Temperatura: {temperature}\n"
        f"- Umidade relativa: {humidity}\n"
        f"- Umidade do substrato: {soil}\n\n"
        f"Avaliacao calculada: {metrics_evaluation}\n"
    )

    _smtp_send(msg)
