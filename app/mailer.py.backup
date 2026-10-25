
"""Send email through Resend API with optional Gmail SMTP fallback."""

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


def gmail_is_configured():
    cfg = current_app.config
    return bool(
        cfg.get("MAIL_SERVER")
        and cfg.get("MAIL_PORT")
        and cfg.get("MAIL_USERNAME")
        and cfg.get("MAIL_PASSWORD")
        and cfg.get("MAIL_SENDER")
    )


def mail_is_configured():
    """Return True if at least one email service is configured."""
    return resend_is_configured() or gmail_is_configured()


def _send_with_resend(to_address, subject, text_body, html_body=None):
    """Send email using the Resend API and report useful errors."""
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
        # Include Resend's explanation, but never log the API key.
        try:
            data = response.json()
            detail = (
                data.get("message")
                or data.get("error")
                or "No additional details provided"
            )
        except (ValueError, AttributeError):
            detail = "No additional details provided"

        raise MailSendError(
            f"Resend returned HTTP {response.status_code}: {detail}"
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

    use_ssl = str(cfg.get("MAIL_USE_SSL", False)).lower() == "true"
    use_tls = str(cfg.get("MAIL_USE_TLS", True)).lower() == "true"

    if use_ssl:
        smtp_class = smtplib.SMTP_SSL
    else:
        smtp_class = smtplib.SMTP

    with smtp_class(
        cfg["MAIL_SERVER"],
        int(cfg["MAIL_PORT"]),
        timeout=20,
    ) as server:
        server.ehlo()

        if use_tls and not use_ssl:
            server.starttls()
            server.ehlo()

        server.login(
            cfg["MAIL_USERNAME"],
            cfg["MAIL_PASSWORD"],
        )
        server.send_message(message)


def send_mail(to_address, subject, text_body, html_body=None):
    """Try Resend first, then Gmail SMTP if configured."""
    if not mail_is_configured():
        raise MailNotConfigured(
            "Configure Resend or Gmail SMTP before sending email."
        )

    errors = []

    if resend_is_configured():
        try:
            _send_with_resend(
                to_address, subject, text_body, html_body
            )
            current_app.logger.info(
                "Email sent successfully through Resend."
            )
            return

        except (requests.RequestException, MailSendError) as error:
            errors.append(f"Resend: {error}")
            current_app.logger.warning(
                "Resend delivery failed: %s",
                error,
            )

    if gmail_is_configured():
        try:
            _send_with_gmail(
                to_address, subject, text_body, html_body
            )
            current_app.logger.info(
                "Email sent successfully through Gmail SMTP."
            )
            return

        except (smtplib.SMTPException, OSError) as error:
            errors.append(f"Gmail SMTP: {error}")
            current_app.logger.error(
                "Gmail SMTP delivery failed: %s",
                error,
            )

    # Keep the detailed diagnostic in server logs. Avoid exposing
    # provider details to end users through exception messages.
    current_app.logger.error(
        "All configured email delivery methods failed: %s",
        " | ".join(errors),
    )

    raise MailSendError(
        "The email could not be sent. Please try again later."
    )
