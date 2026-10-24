
"""Send email through Resend API with Gmail SMTP fallback."""

import smtplib
from email.message import EmailMessage

import requests
from flask import current_app


class MailNotConfigured(Exception):
    """Email settings are missing."""


class MailSendError(Exception):
    """Email could not be sent."""


def resend_is_configured():
    cfg = current_app.config
    return bool(
        cfg.get("RESEND_API_KEY")
        and cfg.get("RESEND_FROM_EMAIL")
    )


def mail_is_configured():
    """Return True if either email service is configured."""
    cfg = current_app.config

    resend_ready = resend_is_configured()

    gmail_ready = bool(
        cfg.get("MAIL_SERVER")
        and cfg.get("MAIL_PORT")
        and cfg.get("MAIL_USERNAME")
        and cfg.get("MAIL_PASSWORD")
        and cfg.get("MAIL_SENDER")
    )

    return resend_ready or gmail_ready


def _send_with_resend(to_address, subject, text_body, html_body=None):
    """Send email through the Resend API."""
    cfg = current_app.config

    payload = {
        "from": cfg["RESEND_FROM_EMAIL"],
        "to": [to_address],
        "subject": subject,
        "text": text_body,
    }

    if html_body:
        payload["html"] = html_body

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {cfg['RESEND_API_KEY']}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20,
    )

    if not response.ok:
        raise RuntimeError(
            f"Resend API returned HTTP {response.status_code}"
        )


def _send_with_gmail(to_address, subject, text_body, html_body=None):
    """Send email through Gmail SMTP."""
    cfg = current_app.config

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = cfg["MAIL_SENDER"]
    message["To"] = to_address
    message.set_content(text_body)

    if html_body:
        message.add_alternative(html_body, subtype="html")

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


def send_mail(to_address, subject, text_body, html_body=None):
    """Try Resend first, then Gmail SMTP as fallback."""
    cfg = current_app.config

    if not mail_is_configured():
        raise MailNotConfigured(
            "Configure Resend or Gmail SMTP before sending email"
        )

    if resend_is_configured():
        try:
            _send_with_resend(
                to_address, subject, text_body, html_body
            )
            current_app.logger.info("Email sent successfully through Resend")
            return

        except (requests.RequestException, RuntimeError) as error:
            current_app.logger.warning(
                "Resend failed; trying Gmail SMTP. Error: %s",
                str(error),
            )

    gmail_ready = bool(
        cfg.get("MAIL_SERVER")
        and cfg.get("MAIL_PORT")
        and cfg.get("MAIL_USERNAME")
        and cfg.get("MAIL_PASSWORD")
        and cfg.get("MAIL_SENDER")
    )

    if gmail_ready:
        try:
            _send_with_gmail(
                to_address, subject, text_body, html_body
            )
            current_app.logger.info(
                "Email sent successfully through Gmail SMTP")
            return

        except (smtplib.SMTPException, OSError) as error:
            current_app.logger.error(
                "Gmail SMTP failed: %s", str(error)
            )
            raise MailSendError(
                "Resend and Gmail SMTP could not send the email"
            ) from error

    raise MailSendError(
        "Resend failed and Gmail SMTP is not configured"
    )
