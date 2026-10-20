
"""Send email through the Resend HTTPS API."""

import requests
from flask import current_app


class MailNotConfigured(Exception):
    """Email API settings are missing."""


class MailSendError(Exception):
    """The email API rejected or could not deliver the message."""


def mail_is_configured():
    cfg = current_app.config
    return bool(
        cfg.get("RESEND_API_KEY")
        and cfg.get("RESEND_FROM_EMAIL")
    )


def send_mail(to_address, subject, text_body, html_body=None):
    """Send one email through Resend's HTTPS API."""
    cfg = current_app.config

    if not mail_is_configured():
        raise MailNotConfigured("Resend is not configured")

    payload = {
        "from": cfg["RESEND_FROM_EMAIL"],
        "to": [to_address],
        "subject": subject,
        "text": text_body,
    }

    if html_body:
        payload["html"] = html_body

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {cfg['RESEND_API_KEY']}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )

        if not response.ok:
            current_app.logger.error(
                "Resend email API failed: HTTP %s",
                response.status_code,
            )
            raise MailSendError(
                f"Resend API returned HTTP {response.status_code}"
            )

        current_app.logger.info("Resend accepted an email request")

    except requests.RequestException as error:
        current_app.logger.error(
            "Resend request failed: %s",
            type(error).__name__,
        )
        raise MailSendError(type(error).__name__) from error
