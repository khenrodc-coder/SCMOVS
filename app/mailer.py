"""Send email through SMTP (standard library only). Credentials come from .env via config.py."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from flask import current_app


class MailNotConfigured(Exception):
    """SMTP settings are missing in .env."""


class MailSendError(Exception):
    """The SMTP server rejected or could not deliver the message."""


def mail_is_configured():
    cfg = current_app.config
    return bool(cfg["MAIL_SERVER"] and cfg["MAIL_SENDER"] and cfg["MAIL_USERNAME"] and cfg["MAIL_PASSWORD"])


def send_mail(to_address, subject, text_body, html_body=None):
    """Send one email. Raises MailNotConfigured or MailSendError; never returns success silently."""
    cfg = current_app.config
    if not mail_is_configured():
        raise MailNotConfigured("SMTP is not configured")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((current_app.config["SYSTEM_NAME"] + " Support", cfg["MAIL_SENDER"]))
    message["To"] = to_address
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        context = ssl.create_default_context()
        if cfg["MAIL_USE_SSL"]:
            server = smtplib.SMTP_SSL(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15, context=context)
        else:
            server = smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15)
        with server:
            if not cfg["MAIL_USE_SSL"] and cfg["MAIL_USE_TLS"]:
                server.starttls(context=context)
            server.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as error:
        # Log the error TYPE only: messages can echo the username, and the password must never be logged.
        current_app.logger.error("SMTP send failed: %s", type(error).__name__)
        raise MailSendError(type(error).__name__) from error
