# e-mails transacionais: MFA, alertas de estufa e convites

from __future__ import annotations

import smtplib
from datetime import datetime
from email.message import EmailMessage
from html import escape

from app.config.settings import settings


def _format_mfa_expiry(expires_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return parsed.strftime("%d/%m/%Y %H:%M UTC")
    except Exception:
        return expires_at


def _smtp_send(message: EmailMessage) -> None:
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
    expiry_label = _format_mfa_expiry(expires_at)
    logo_url = settings.mfa_email_logo_url
    logo_html = (
        f'<img src="{escape(logo_url)}" alt="Plantelligence" '
        'style="display:block;height:34px;max-width:180px;object-fit:contain;margin:0 auto 10px;" />'
        if logo_url
        else '<p style="margin:0 0 10px;font:700 18px/1.2 Arial,sans-serif;letter-spacing:.08em;color:#991b1b;">PLANTELLIGENCE</p>'
    )

    html_body = (
        "<!doctype html>"
        "<html lang=\"pt-BR\">"
        "<body style=\"margin:0;padding:0;background:#f3f4f6;\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#f3f4f6;padding:24px 12px;\">"
        "<tr><td align=\"center\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"max-width:560px;background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;\">"
        "<tr><td style=\"padding:24px 24px 18px;text-align:center;background:linear-gradient(180deg,#fff 0%,#fff7f7 100%);\">"
        f"{logo_html}"
        "<p style=\"margin:0;font:600 14px/1.4 Arial,sans-serif;color:#374151;\">Código de verificação de acesso</p>"
        "</td></tr>"
        "<tr><td style=\"padding:22px 24px 6px;\">"
        "<h1 style=\"margin:0 0 12px;font:700 24px/1.25 Arial,sans-serif;color:#111827;text-align:center;\">Seu código MFA</h1>"
        "<p style=\"margin:0 0 16px;font:400 15px/1.6 Arial,sans-serif;color:#374151;text-align:center;\">"
        "Use o código abaixo para concluir o acesso com autenticação em dois fatores."
        "</p>"
        "<div style=\"margin:0 auto 16px;max-width:240px;border:1px dashed #f43f5e;background:#fff1f2;border-radius:10px;padding:14px 12px;text-align:center;\">"
        f"<p style=\"margin:0;font:700 34px/1.1 'Courier New',monospace;letter-spacing:.18em;color:#be123c;\">{escape(code)}</p>"
        "</div>"
        f"<p style=\"margin:0 0 18px;font:600 13px/1.4 Arial,sans-serif;color:#6b7280;text-align:center;\">Válido até {escape(expiry_label)}</p>"
        "<p style=\"margin:0;font:400 14px/1.6 Arial,sans-serif;color:#374151;\">"
        "Se você não solicitou este código, ignore este e-mail e troque sua senha assim que possível. "
        "Não compartilhe este código com ninguém."
        "</p>"
        "</td></tr>"
        "<tr><td style=\"padding:16px 24px 24px;\">"
        "<p style=\"margin:0;font:400 12px/1.6 Arial,sans-serif;color:#9ca3af;text-align:center;\">"
        "Este e-mail foi enviado automaticamente pela segurança da conta Plantelligence."
        "</p>"
        "</td></tr>"
        "</table>"
        "</td></tr></table>"
        "</body></html>"
    )

    msg = EmailMessage()
    msg["From"] = settings.resolved_smtp_from
    msg["To"] = to
    msg["Subject"] = "Plantelligence - Código de autenticação multifator"
    msg.set_content(
        "Código de verificação MFA - Plantelligence\n\n"
        f"Seu código de verificação: {code}\n"
        f"Validade: {expiry_label}\n\n"
        "Se você não solicitou este código, ignore esta mensagem e revise a segurança da conta.\n"
        "Nunca compartilhe este código com terceiros."
    )
    msg.add_alternative(html_body, subtype="html")
    _smtp_send(msg)


def send_greenhouse_alert_email(
    recipients: list[str],
    greenhouse_name: str,
    profile: dict,
    metrics: dict,
    metrics_evaluation: dict,
    metric_sources: dict | None,
    partial_evaluation: bool,
    alerts: list[str],
) -> None:
    if not recipients:
        return

    msg = EmailMessage()
    msg["From"] = settings.resolved_smtp_from or "Plantelligence <noreply@plantelligence.cloud>"
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = f"Plantelligence - Alerta crítico na estufa {greenhouse_name}"

    temperature = metrics.get("temperature", "n/d")
    humidity = metrics.get("humidity", "n/d")
    soil = metrics.get("soilMoisture", "n/d")
    alerts_text = "\n".join(f"- {item}" for item in alerts)

    sources = metric_sources or {}
    source_map = {
        "internal": "Sensor interno",
        "external": "Clima da cidade",
        "unavailable": "Nao informado",
    }

    metric_labels = {
        "temperature": "Temperatura",
        "humidity": "Umidade relativa",
        "soilMoisture": "Luminosidade (proxy operacional)",
    }
    metric_units = {
        "temperature": "°C",
        "humidity": "%",
        "soilMoisture": " lux",
    }

    def _format_value(value: object, metric_name: str) -> str:
        if value is None or value == "n/d":
            return "n/d"
        try:
            parsed = float(value)
            return f"{parsed:.1f}{metric_units.get(metric_name, '')}"
        except Exception:
            return str(value)

    def _format_expected(expected: object, metric_name: str) -> str:
        if not isinstance(expected, dict):
            return "n/d"
        min_value = expected.get("min")
        max_value = expected.get("max")
        if min_value is None or max_value is None:
            return "n/d"
        unit = metric_units.get(metric_name, "")
        return f"{min_value} - {max_value}{unit}"

    def _status_text(evaluation: dict | None) -> str:
        if not isinstance(evaluation, dict):
            return "n/d"
        if not evaluation.get("evaluated"):
            return "sem dados"
        if evaluation.get("ok"):
            return "dentro da faixa"
        if evaluation.get("direction") == "low":
            return "abaixo da faixa"
        if evaluation.get("direction") == "high":
            return "acima da faixa"
        return "fora da faixa"

    rows = []
    for metric_name in ("temperature", "humidity", "soilMoisture"):
        evaluation = metrics_evaluation.get(metric_name) if isinstance(metrics_evaluation, dict) else None
        expected = evaluation.get("expected") if isinstance(evaluation, dict) else None
        value = evaluation.get("value") if isinstance(evaluation, dict) else metrics.get(metric_name)
        origin = source_map.get((sources.get(metric_name) or "").lower(), "Nao informado")
        rows.append(
            {
                "label": metric_labels[metric_name],
                "value": _format_value(value, metric_name),
                "expected": _format_expected(expected, metric_name),
                "status": _status_text(evaluation),
                "source": origin,
            }
        )

    evaluation_rows_html = "".join(
        "<tr>"
        f"<td style=\"padding:8px 10px;border-bottom:1px solid #e5e7eb;font:600 12px Arial,sans-serif;color:#374151;\">{escape(row['label'])}</td>"
        f"<td style=\"padding:8px 10px;border-bottom:1px solid #e5e7eb;font:700 12px Arial,sans-serif;color:#111827;text-align:right;\">{escape(row['value'])}</td>"
        f"<td style=\"padding:8px 10px;border-bottom:1px solid #e5e7eb;font:500 12px Arial,sans-serif;color:#374151;text-align:right;\">{escape(row['expected'])}</td>"
        f"<td style=\"padding:8px 10px;border-bottom:1px solid #e5e7eb;font:500 12px Arial,sans-serif;color:#374151;text-align:right;\">{escape(row['status'])}</td>"
        f"<td style=\"padding:8px 10px;border-bottom:1px solid #e5e7eb;font:500 12px Arial,sans-serif;color:#6b7280;text-align:right;\">{escape(row['source'])}</td>"
        "</tr>"
        for row in rows
    )

    partial_notice_html = (
        "<p style=\"margin:0 0 10px;font:600 12px/1.5 Arial,sans-serif;color:#7c2d12;\">"
        "Avaliacao parcial: devido a fase atual de implantacao, o sistema usa principalmente dados climaticos externos (clima da cidade) e apenas os sensores internos que ja estiverem ativos."
        "</p>"
        if partial_evaluation
        else ""
    )

    logo_url = settings.mfa_email_logo_url
    logo_html = (
        f'<img src="{escape(logo_url)}" alt="Plantelligence" '
        'style="display:block;height:34px;max-width:180px;object-fit:contain;margin:0 auto 10px;" />'
        if logo_url
        else '<p style="margin:0 0 10px;font:700 18px/1.2 Arial,sans-serif;letter-spacing:.08em;color:#991b1b;">PLANTELLIGENCE</p>'
    )

    alert_items_html = "".join(
        f'<li style="margin:0 0 6px;color:#b91c1c;font:600 13px/1.5 Arial,sans-serif;">{escape(item)}</li>'
        for item in alerts
    ) or '<li style="margin:0;color:#374151;font:500 13px/1.5 Arial,sans-serif;">Sem descrição adicional.</li>'

    html_body = (
        "<!doctype html>"
        "<html lang=\"pt-BR\">"
        "<body style=\"margin:0;padding:0;background:#f3f4f6;\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#f3f4f6;padding:24px 12px;\">"
        "<tr><td align=\"center\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"max-width:620px;background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;\">"
        "<tr><td style=\"padding:24px 24px 18px;text-align:center;background:linear-gradient(180deg,#fff 0%,#fff7f7 100%);\">"
        f"{logo_html}"
        "<p style=\"margin:0;font:600 14px/1.4 Arial,sans-serif;color:#374151;\">Alerta operacional de estufa</p>"
        "</td></tr>"
        "<tr><td style=\"padding:20px 24px 8px;\">"
        "<h1 style=\"margin:0 0 10px;font:700 23px/1.25 Arial,sans-serif;color:#111827;\">Ação necessária na estufa</h1>"
        f"<p style=\"margin:0 0 6px;font:600 14px/1.5 Arial,sans-serif;color:#1f2937;\">Estufa: {escape(greenhouse_name)}</p>"
        f"<p style=\"margin:0 0 14px;font:400 13px/1.5 Arial,sans-serif;color:#6b7280;\">Perfil: {escape(str(profile.get('name') or 'Perfil não informado'))}</p>"
        f"{partial_notice_html}"
        "<div style=\"border:1px solid #fecaca;background:#fff1f2;border-radius:10px;padding:12px 14px;margin-bottom:14px;\">"
        "<p style=\"margin:0 0 8px;font:700 12px/1.4 Arial,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#9f1239;\">Resumo do alerta</p>"
        f"<ul style=\"margin:0;padding-left:18px;\">{alert_items_html}</ul>"
        "</div>"
        "<p style=\"margin:0 0 8px;font:700 12px/1.4 Arial,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#6b7280;\">Comparativo tecnico (atual x ideal)</p>"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;\">"
        "<tr>"
        "<td style=\"padding:8px 10px;border-bottom:1px solid #e5e7eb;font:700 12px Arial,sans-serif;color:#111827;\">Parametro</td>"
        "<td style=\"padding:8px 10px;border-bottom:1px solid #e5e7eb;font:700 12px Arial,sans-serif;color:#111827;text-align:right;\">Atual</td>"
        "<td style=\"padding:8px 10px;border-bottom:1px solid #e5e7eb;font:700 12px Arial,sans-serif;color:#111827;text-align:right;\">Ideal</td>"
        "<td style=\"padding:8px 10px;border-bottom:1px solid #e5e7eb;font:700 12px Arial,sans-serif;color:#111827;text-align:right;\">Status</td>"
        "<td style=\"padding:8px 10px;border-bottom:1px solid #e5e7eb;font:700 12px Arial,sans-serif;color:#111827;text-align:right;\">Fonte</td>"
        "</tr>"
        f"{evaluation_rows_html}"
        "</table>"
        "</td></tr>"
        "<tr><td style=\"padding:12px 24px 20px;\">"
        "<p style=\"margin:0;font:400 12px/1.6 Arial,sans-serif;color:#6b7280;\">"
        "Este e-mail foi enviado automaticamente pela plataforma Plantelligence para a equipe responsável delegada da estufa."
        "</p>"
        "</td></tr>"
        "</table>"
        "</td></tr></table>"
        "</body></html>"
    )

    msg.set_content(
        "Equipe Plantelligence,\n\n"
        f"Detectamos desvios na estufa '{greenhouse_name}' ({profile.get('name')}).\n\n"
        f"Avaliacao parcial: {'sim' if partial_evaluation else 'nao'}\n\n"
        + (
            "Observacao: devido a fase atual de implantacao, a avaliacao usa principalmente dados climaticos externos (clima da cidade) e somente sensores internos ja habilitados.\n\n"
            if partial_evaluation
            else ""
        )
        +
        f"Resumo:\n{alerts_text}\n\n"
        "Comparativo tecnico:\n"
        + "\n".join(
            f"- {row['label']}: atual={row['value']} | ideal={row['expected']} | status={row['status']} | fonte={row['source']}"
            for row in rows
        )
        + "\n\n"
        f"Avaliacao calculada: {metrics_evaluation}\n"
    )
    msg.add_alternative(html_body, subtype="html")

    _smtp_send(msg)


def send_user_invitation_email(to: str, invite_link: str, expires_at: str, role_label: str) -> None:
    expiry_label = _format_mfa_expiry(expires_at)
    logo_url = settings.mfa_email_logo_url
    logo_html = (
        f'<img src="{escape(logo_url)}" alt="Plantelligence" '
        'style="display:block;height:34px;max-width:180px;object-fit:contain;margin:0 auto 10px;" />'
        if logo_url
        else '<p style="margin:0 0 10px;font:700 18px/1.2 Arial,sans-serif;letter-spacing:.08em;color:#991b1b;">PLANTELLIGENCE</p>'
    )

    safe_link = escape(invite_link)
    safe_role = escape(role_label)

    html_body = (
        "<!doctype html>"
        "<html lang=\"pt-BR\">"
        "<body style=\"margin:0;padding:0;background:#f3f4f6;\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#f3f4f6;padding:24px 12px;\">"
        "<tr><td align=\"center\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"max-width:560px;background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;\">"
        "<tr><td style=\"padding:24px 24px 18px;text-align:center;background:linear-gradient(180deg,#fff 0%,#fff7f7 100%);\">"
        f"{logo_html}"
        "<p style=\"margin:0;font:600 14px/1.4 Arial,sans-serif;color:#374151;\">Convite para entrar na organização</p>"
        "</td></tr>"
        "<tr><td style=\"padding:22px 24px 8px;\">"
        "<h1 style=\"margin:0 0 12px;font:700 24px/1.25 Arial,sans-serif;color:#111827;text-align:center;\">Você foi convidado(a)</h1>"
        "<p style=\"margin:0 0 14px;font:400 15px/1.6 Arial,sans-serif;color:#374151;text-align:center;\">"
        "Seu acesso ao Plantelligence foi criado por um administrador."
        "</p>"
        "<div style=\"margin:0 auto 14px;max-width:360px;border:1px solid #e5e7eb;background:#f9fafb;border-radius:10px;padding:12px 14px;text-align:center;\">"
        f"<p style=\"margin:0;font:600 14px/1.5 Arial,sans-serif;color:#1f2937;\">Perfil inicial: {safe_role}</p>"
        f"<p style=\"margin:4px 0 0;font:500 12px/1.4 Arial,sans-serif;color:#6b7280;\">Link válido até {escape(expiry_label)}</p>"
        "</div>"
        "<div style=\"text-align:center;margin:18px 0 10px;\">"
        f"<a href=\"{safe_link}\" style=\"display:inline-block;background:#dc2626;color:#ffffff;text-decoration:none;padding:12px 18px;border-radius:8px;font:700 14px/1 Arial,sans-serif;\">Definir senha e ativar acesso</a>"
        "</div>"
        "<p style=\"margin:0 0 6px;font:400 12px/1.6 Arial,sans-serif;color:#6b7280;text-align:center;\">"
        "Se o botão não abrir, copie e cole este link no navegador:"
        "</p>"
        f"<p style=\"margin:0;font:400 12px/1.6 Arial,sans-serif;color:#374151;word-break:break-all;text-align:center;\">{safe_link}</p>"
        "</td></tr>"
        "<tr><td style=\"padding:16px 24px 24px;\">"
        "<p style=\"margin:0;font:400 12px/1.6 Arial,sans-serif;color:#9ca3af;text-align:center;\">"
        "Se você não esperava este convite, ignore este e-mail e avise o administrador da sua organização."
        "</p>"
        "</td></tr>"
        "</table>"
        "</td></tr></table>"
        "</body></html>"
    )

    msg = EmailMessage()
    msg["From"] = settings.resolved_smtp_from
    msg["To"] = to
    msg["Subject"] = "Plantelligence - Convite para sua organização"
    msg.set_content(
        "Você recebeu um convite para acessar o Plantelligence.\n\n"
        f"Perfil inicial: {role_label}\n"
        f"Link para definir sua senha: {invite_link}\n"
        f"Validade do link: {expiry_label}\n\n"
        "Se você não esperava este convite, ignore esta mensagem e avise o administrador do sistema."
    )
    msg.add_alternative(html_body, subtype="html")
    _smtp_send(msg)


def send_contact_request_email(
    name: str,
    email: str,
    company: str | None,
    subject: str,
    message: str,
) -> None:
    msg = EmailMessage()
    msg["From"] = settings.resolved_smtp_from
    msg["To"] = "contato@plantelligence.cloud"
    msg["Reply-To"] = email
    msg["Subject"] = f"[Fale Conosco] {subject}"

    company_text = company or "Não informado"

    logo_url = settings.mfa_email_logo_url
    logo_html = (
        f'<img src="{escape(logo_url)}" alt="Plantelligence" '
        'style="display:block;height:34px;max-width:180px;object-fit:contain;margin:0 auto 10px;" />'
        if logo_url
        else '<p style="margin:0 0 10px;font:700 18px/1.2 Arial,sans-serif;letter-spacing:.08em;color:#991b1b;">PLANTELLIGENCE</p>'
    )

    html_body = (
        "<!doctype html>"
        "<html lang=\"pt-BR\">"
        "<body style=\"margin:0;padding:0;background:#f3f4f6;\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#f3f4f6;padding:24px 12px;\">"
        "<tr><td align=\"center\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"max-width:560px;background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;\">"
        "<tr><td style=\"padding:24px 24px 18px;text-align:center;background:linear-gradient(180deg,#fff 0%,#fff7f7 100%);\">"
        f"{logo_html}"
        "<p style=\"margin:0;font:600 14px/1.4 Arial,sans-serif;color:#374151;\">Solicitação de contato via site</p>"
        "</td></tr>"
        "<tr><td style=\"padding:20px 24px 8px;\">"
        "<h1 style=\"margin:0 0 14px;font:700 22px/1.25 Arial,sans-serif;color:#111827;\">Nova mensagem recebida</h1>"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;margin-bottom:16px;\">"
        "<tr>"
        "<td style=\"padding:10px 14px;border-bottom:1px solid #e5e7eb;background:#f9fafb;width:90px;\"><span style=\"font:700 12px Arial,sans-serif;color:#374151;\">Nome</span></td>"
        f"<td style=\"padding:10px 14px;border-bottom:1px solid #e5e7eb;\"><span style=\"font:400 13px Arial,sans-serif;color:#111827;\">{escape(name)}</span></td>"
        "</tr>"
        "<tr>"
        "<td style=\"padding:10px 14px;border-bottom:1px solid #e5e7eb;background:#f9fafb;\"><span style=\"font:700 12px Arial,sans-serif;color:#374151;\">E-mail</span></td>"
        f"<td style=\"padding:10px 14px;border-bottom:1px solid #e5e7eb;\"><span style=\"font:400 13px Arial,sans-serif;color:#111827;\">{escape(email)}</span></td>"
        "</tr>"
        "<tr>"
        "<td style=\"padding:10px 14px;border-bottom:1px solid #e5e7eb;background:#f9fafb;\"><span style=\"font:700 12px Arial,sans-serif;color:#374151;\">Empresa</span></td>"
        f"<td style=\"padding:10px 14px;border-bottom:1px solid #e5e7eb;\"><span style=\"font:400 13px Arial,sans-serif;color:#6b7280;\">{escape(company_text)}</span></td>"
        "</tr>"
        "<tr>"
        "<td style=\"padding:10px 14px;border-bottom:1px solid #e5e7eb;background:#f9fafb;\"><span style=\"font:700 12px Arial,sans-serif;color:#374151;\">Assunto</span></td>"
        f"<td style=\"padding:10px 14px;border-bottom:1px solid #e5e7eb;\"><span style=\"font:400 13px Arial,sans-serif;color:#111827;\">{escape(subject)}</span></td>"
        "</tr>"
        "</table>"
        "<p style=\"margin:0 0 8px;font:700 12px/1.4 Arial,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#6b7280;\">Mensagem</p>"
        "<div style=\"border:1px solid #e5e7eb;border-radius:10px;padding:14px;background:#f9fafb;\">"
        f"<p style=\"margin:0;font:400 14px/1.7 Arial,sans-serif;color:#374151;white-space:pre-wrap;\">{escape(message)}</p>"
        "</div>"
        "</td></tr>"
        "<tr><td style=\"padding:16px 24px 24px;\">"
        "<p style=\"margin:0;font:400 12px/1.6 Arial,sans-serif;color:#9ca3af;text-align:center;\">"
        "Esta mensagem foi enviada via formulário de contato do Plantelligence."
        "</p>"
        "</td></tr>"
        "</table>"
        "</td></tr></table>"
        "</body></html>"
    )

    msg.set_content(
        "Nova solicitacao recebida via pagina Fale Conosco.\n\n"
        f"Nome: {name}\n"
        f"E-mail: {email}\n"
        f"Empresa: {company_text}\n\n"
        "Mensagem:\n"
        f"{message}\n"
    )
    msg.add_alternative(html_body, subtype="html")
    _smtp_send(msg)


def send_contact_confirmation_email(name: str, email: str, subject: str) -> None:
    logo_url = settings.mfa_email_logo_url
    logo_html = (
        f'<img src="{escape(logo_url)}" alt="Plantelligence" '
        'style="display:block;height:34px;max-width:180px;object-fit:contain;margin:0 auto 10px;" />'
        if logo_url
        else '<p style="margin:0 0 10px;font:700 18px/1.2 Arial,sans-serif;letter-spacing:.08em;color:#991b1b;">PLANTELLIGENCE</p>'
    )

    html_body = (
        "<!doctype html>"
        "<html lang=\"pt-BR\">"
        "<body style=\"margin:0;padding:0;background:#f3f4f6;\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#f3f4f6;padding:24px 12px;\">"
        "<tr><td align=\"center\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"max-width:560px;background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;\">"
        "<tr><td style=\"padding:24px 24px 18px;text-align:center;background:linear-gradient(180deg,#fff 0%,#fff7f7 100%);\">"
        f"{logo_html}"
        "<p style=\"margin:0;font:600 14px/1.4 Arial,sans-serif;color:#374151;\">Confirmação de contato</p>"
        "</td></tr>"
        "<tr><td style=\"padding:22px 24px 8px;\">"
        f"<h1 style=\"margin:0 0 12px;font:700 22px/1.25 Arial,sans-serif;color:#111827;\">Olá, {escape(name.split()[0])}!</h1>"
        "<p style=\"margin:0 0 14px;font:400 15px/1.7 Arial,sans-serif;color:#374151;\">"
        "Recebemos sua mensagem e ela já está com nossa equipe. "
        "Em breve um especialista entrará em contato com você por este e-mail."
        "</p>"
        "<div style=\"border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;background:#f9fafb;margin-bottom:16px;\">"
        f"<p style=\"margin:0 0 4px;font:700 12px Arial,sans-serif;color:#6b7280;text-transform:uppercase;letter-spacing:.06em;\">Assunto registrado</p>"
        f"<p style=\"margin:0;font:400 14px/1.5 Arial,sans-serif;color:#111827;\">{escape(subject)}</p>"
        "</div>"
        "<p style=\"margin:0;font:400 14px/1.7 Arial,sans-serif;color:#374151;\">"
        "Se precisar de algo com urgência, você também pode nos escrever diretamente em "
        "<a href=\"mailto:contato@plantelligence.cloud\" style=\"color:#dc2626;text-decoration:none;\">contato@plantelligence.cloud</a>."
        "</p>"
        "</td></tr>"
        "<tr><td style=\"padding:16px 24px 24px;\">"
        "<p style=\"margin:0;font:400 12px/1.6 Arial,sans-serif;color:#9ca3af;text-align:center;\">"
        "Este e-mail foi enviado automaticamente. Por favor, não responda diretamente a esta mensagem."
        "</p>"
        "</td></tr>"
        "</table>"
        "</td></tr></table>"
        "</body></html>"
    )

    msg = EmailMessage()
    msg["From"] = settings.resolved_smtp_from
    msg["To"] = email
    msg["Subject"] = "Recebemos sua mensagem — Plantelligence"
    msg.set_content(
        f"Olá, {name.split()[0]}!\n\n"
        "Recebemos sua mensagem e ela já está com nossa equipe.\n"
        "Em breve um especialista entrará em contato com você por este e-mail.\n\n"
        f"Assunto registrado: {subject}\n\n"
        "Se precisar de algo com urgência, escreva para contato@plantelligence.cloud.\n"
    )
    msg.add_alternative(html_body, subtype="html")
    _smtp_send(msg)
