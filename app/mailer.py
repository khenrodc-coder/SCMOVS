
"""Send email through Resend, Gmail API, or optional Gmail SMTP."""

import base64
import os
import smtplib
from email.message import EmailMessage

import requests
from flask import current_app


class MailNotConfigured(Exception):
    """Email settings are missing."""


class MailSendError(Exception):
    """Email could not be sent."""


def _setting(name, default=None):
    """Read a setting from Flask config or environment variables."""
    return current_app.config.get(name) or os.environ.get(name) or default


def resend_is_configured():
    return bool(
        _setting("RESEND_API_KEY")
        and _setting("RESEND_FROM_EMAIL")
    )


def gmail_api_is_configured():
    return bool(
        _setting("GMAIL_OAUTH_CLIENT_ID")
        and _setting("GMAIL_OAUTH_CLIENT_SECRET")
        and _setting("GMAIL_OAUTH_REFRESH_TOKEN")
        and _setting("GMAIL_SENDER_EMAIL")
    )


def gmail_smtp_is_configured():
    return bool(
        _setting("MAIL_SERVER")
        and _setting("MAIL_PORT")
        and _setting("MAIL_USERNAME")
        and _setting("MAIL_PASSWORD")
        and _setting("MAIL_SENDER")
    )


def mail_is_configured():
    return (
        resend_is_configured()
        or gmail_api_is_configured()
        or gmail_smtp_is_configured()
    )


def _send_with_resend(to_address, subject, text_body, html_body=None):
    """Send email using Resend."""
    payload = {
        "from": _setting("RESEND_FROM_EMAIL"),
        "to": [to_address],
        "subject": subject,
        "text": text_body,
    }

    if html_body:
        payload["html"] = html_body

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {_setting('RESEND_API_KEY')}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20,
    )

    if not response.ok:
        try:
            data = response.json()
            detail = data.get("message") or data.get("error") or response.text
        except ValueError:
            detail = response.text

        raise MailSendError(
            f"Resend returned HTTP {response.status_code}: {detail[:300]}"
        )


def _send_with_gmail_api(to_address, subject, text_body, html_body=None):
    """Send email through Gmail API using an OAuth refresh token."""
    client_id = _setting("GMAIL_OAUTH_CLIENT_ID")
    client_secret = _setting("GMAIL_OAUTH_CLIENT_SECRET")
    refresh_token = _setting("GMAIL_OAUTH_REFRESH_TOKEN")
    sender_email = _setting("GMAIL_SENDER_EMAIL")

    # Exchange the refresh token for a short-lived access token.
    token_response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )

    if not token_response.ok:
        try:
            detail = token_response.json().get("error_description") or (
                token_response.json().get("error")
            )
        except ValueError:
            detail = token_response.text

        raise MailSendError(
            f"Google token request failed "
            f"(HTTP {token_response.status_code}): {str(detail)[:300]}"
        )

    access_token = token_response.json().get("access_token")
    if not access_token:
        raise MailSendError("Google did not return an access token.")

    # Build the email, including HTML when supplied.
    message = EmailMessage()
    message["To"] = to_address
    message["From"] = sender_email
    message["Subject"] = subject
    message.set_content(text_body)

    if html_body:
        message.add_alternative(html_body, subtype="html")

    # Gmail API expects a base64url-encoded RFC 2822 message.
    raw_message = base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode("ascii")

    send_response = requests.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"raw": raw_message},
        timeout=20,
    )

    if not send_response.ok:
        try:
            data = send_response.json()
            detail = data.get("error", {}).get("message") or send_response.text
        except (ValueError, AttributeError):
            detail = send_response.text

        raise MailSendError(
            f"Gmail API returned HTTP {send_response.status_code}: "
            f"{str(detail)[:300]}"
        )


def _send_with_gmail_smtp(to_address, subject, text_body, html_body=None):
    """Optional fallback using the existing Gmail SMTP configuration."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _setting("MAIL_SENDER")
    message["To"] = to_address
    message.set_content(text_body)

    if html_body:
        message.add_alternative(html_body, subtype="html")

    use_ssl = str(_setting("MAIL_USE_SSL", "false")).lower() == "true"
    use_tls = str(_setting("MAIL_USE_TLS", "true")).lower() == "true"

    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP

    with smtp_class(
        _setting("MAIL_SERVER"),
        int(_setting("MAIL_PORT", 587)),
        timeout=20,
    ) as server:
        server.ehlo()

        if use_tls and not use_ssl:
            server.starttls()
            server.ehlo()

        server.login(
            _setting("MAIL_USERNAME"),
            _setting("MAIL_PASSWORD"),
        )
        server.send_message(message)


def send_mail(to_address, subject, text_body, html_body=None):
    """Try Resend, then Gmail API, then optional Gmail SMTP."""
    if not mail_is_configured():
        raise MailNotConfigured(
            "Configure Resend, Gmail API, or Gmail SMTP before sending email."
        )

    errors = []

    methods = []

    if resend_is_configured():
        methods.append(("Resend", _send_with_resend))

    if gmail_api_is_configured():
        methods.append(("Gmail API", _send_with_gmail_api))

    if gmail_smtp_is_configured():
        methods.append(("Gmail SMTP", _send_with_gmail_smtp))

    for name, sender in methods:
        try:
            sender(to_address, subject, text_body, html_body)
            current_app.logger.info("Email sent successfully through %s.", name)
            return
        except (requests.RequestException, MailSendError, smtplib.SMTPException, OSError) as error:
            errors.append(f"{name}: {error}")
            current_app.logger.warning("%s delivery failed: %s", name, error)

    current_app.logger.error(
        "All configured email delivery methods failed: %s",
        " | ".join(errors),
    )

    raise MailSendError(
        "The email could not be sent. Please try again later."
    )
