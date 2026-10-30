"""Outgoing email for verification and password-reset codes.

With EMAIL_BACKEND=console nothing is sent (codes are only returned to the client in
development/testing). With EMAIL_BACKEND=smtp, messages go through the configured server.
Delivery failures are logged without the code and never break the request.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import AppSettings

logger = logging.getLogger("researchflow.mail")


class Mailer:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return self.settings.email_backend == "smtp" and bool(self.settings.smtp_host)

    def send(self, to: str, subject: str, body: str) -> bool:
        if not self.enabled:
            return False
        s = self.settings
        msg = EmailMessage()
        msg["From"] = s.email_from_address
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            if s.smtp_port == 465:
                server: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
                if s.smtp_use_tls:
                    server.starttls(context=ssl.create_default_context())
            with server:
                if s.smtp_username:
                    server.login(s.smtp_username, s.smtp_password)
                server.send_message(msg)
            return True
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning("Email to %s failed: %s", to, type(exc).__name__)
            return False

    def send_code(self, to: str, purpose: str, code: str) -> bool:
        app = self.settings.app_name
        # The code travels in the URL fragment, which browsers never send to any server or log.
        origin = self.settings.frontend_origin.rstrip("/")
        if purpose == "verify":
            subject = f"Verify your {app} email"
            body = (f"Confirm your email address by opening this link:\n\n{origin}/#/auth/verify/{code}\n\n"
                    f"Or enter this code on the verification screen:\n\n{code}\n\nIt expires in 24 hours.")
        else:
            subject = f"Reset your {app} password"
            body = (f"Someone asked to reset the password for this {app} account.\n\n"
                    f"Choose a new password here:\n\n{origin}/#/auth/reset/{code}\n\n"
                    f"Or enter this code on the 'Forgot password' screen:\n\n{code}\n\n"
                    "The link works once, for 30 minutes. If this wasn't you, ignore this email.")
        return self.send(to, subject, body + "\n")
