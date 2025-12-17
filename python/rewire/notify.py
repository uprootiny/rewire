"""
Rewire notification layer: SMTP-based email delivery.

Dev mode: prints to stdout when no SMTP host configured.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional


@dataclass(frozen=True)
class SMTPConfig:
    """SMTP configuration. Set host=None for dev mode (print-only)."""
    host: Optional[str]
    port: int
    user: Optional[str]
    password: Optional[str]
    from_email: str


class Notifier:
    """Email notifier using stdlib smtplib."""

    def __init__(self, smtp: SMTPConfig) -> None:
        self.smtp = smtp

    def send_email(self, to_email: str, subject: str, body: str) -> None:
        """Send an email. In dev mode (no host), prints instead."""
        if not self.smtp.host:
            print(f"--- EMAIL to={to_email}\nSUBJ: {subject}\n\n{body}\n---")
            return

        msg = EmailMessage()
        msg["From"] = self.smtp.from_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(self.smtp.host, self.smtp.port, timeout=20) as s:
            s.ehlo()
            try:
                s.starttls()
                s.ehlo()
            except smtplib.SMTPException:
                pass
            if self.smtp.user and self.smtp.password:
                s.login(self.smtp.user, self.smtp.password)
            s.send_message(msg)
