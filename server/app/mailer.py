"""Minimal SMTP sender for reconnect notices (M2) and the daily digest (M6).

If SMTP is not configured, send() is a no-op that returns False, so local dev without
mail settings does not crash. We never route mail through Gmail send scopes.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import Settings, get_settings


def send_email(to: str, subject: str, body: str, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not settings.smtp_host or not to:
        return False

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)
    return True
