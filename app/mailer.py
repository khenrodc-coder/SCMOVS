
"""Send email through Gmail SMTP."""

import smtplib
from email.message import EmailMessage
from flask import current_app


class MailNotConfigured(Exception):
    """Email settings are missing."""


class MailSendError(Exception):
    """Email could not be sent."""


def mail_is_configured():
    cfg = current_app.config
    return bool(
        cfg.get("MAIL_SERVER")
        and cfg.get("MAIL_PORT")
        and cfg.get("MAIL_USERNAME")
        and cfg.get("MAIL_PASSWORD")
        and cfg.get("MAIL_SENDER")
    )


def send_mail(to_address, subject, text_body, html_body=None):
    """Send one email through Gmail SMTP."""
    cfg = current_app.config

    if not mail_is_configured():
        raise MailNotConfigured("Gmail SMTP is not configured")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = cfg["MAIL_SENDER"]
    message["To"] = to_address
    message.set_content(text_body)

    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(
            cfg["MAIL_SERVER"],
            int(cfg["MAIL_PORT"]),
            timeout=20,
        ) as server:
            server.ehlo()

            if cfg.get("MAIL_USE_TLS"):
                server.starttls()
                server.ehlo()

            server.login(
                cfg["MAIL_USERNAME"],
                cfg["MAIL_PASSWORD"],
            )
            server.send_message(message)

        current_app.logger.info("Email sent successfully")

    except (smtplib.SMTPException, OSError) as error:
        current_app.logger.error(
            "Gmail SMTP failed: %s",
            type(error).__name__,
        )
        raise MailSendError("Gmail SMTP could not send the email") from error
