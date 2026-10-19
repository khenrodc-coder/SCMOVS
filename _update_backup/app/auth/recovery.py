"""Password recovery: single-use, expiring, hashed reset tokens delivered by email.

Security properties
  * The emailed token is random (256 bits). Only its SHA-256 hash is stored.
  * Tokens expire after PASSWORD_RESET_MINUTES (30) and work once.
  * Requests are rate limited per IP and per account.
  * The reset link is built from PUBLIC_BASE_URL in .env, never from the request's Host header.
  * The password is only changed after a valid token is presented with a valid new password.
"""
import hashlib
import secrets

from flask import current_app
from werkzeug.security import generate_password_hash

from app.audit.services import log_action
from app.db import fetch_one, get_db
from app.mail_templates import reset_email
from app.mailer import MailNotConfigured, MailSendError, mail_is_configured, send_mail
from app.validators import STUDENT_ID_RE, STUDENT_EMAIL_DOMAIN, normalize_email


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_base_url():
    return current_app.config["PUBLIC_BASE_URL"]


def recovery_available():
    """True when email AND the public URL are configured (otherwise reset emails cannot be sent)."""
    return mail_is_configured() and bool(public_base_url())


# ----------------------------------------------------------- eligibility

def find_eligible_user(email):
    """Return the active account registered with this email, or None.

    Student accounts (anyone with a student record) must use <8-digit Student ID>@holycross.edu.ph
    AND the digits must equal the registered Student ID. Administrative accounts just need the
    email they were registered with. Inactive accounts are never eligible.
    """
    email = normalize_email(email)
    if not email:
        return None
    user = fetch_one(
        "SELECT u.id, u.username, u.email, u.full_name, u.is_active, s.student_number "
        "FROM users u LEFT JOIN students s ON s.user_id = u.id WHERE u.email = %s", (email,))
    if user is None or not user["is_active"]:
        return None
    if user["student_number"] is not None:
        number = user["student_number"]
        local, _, domain = email.partition("@")
        if domain != STUDENT_EMAIL_DOMAIN or not STUDENT_ID_RE.fullmatch(local) or local != number:
            return None
    return user


# ----------------------------------------------------------- rate limits

def _rate_limited(ip, user_id):
    cfg = current_app.config
    row = fetch_one("SELECT COUNT(*) AS n FROM password_reset_requests "
                    "WHERE ip_address = %s AND created_at > DATE_SUB(NOW(), INTERVAL 15 MINUTE)", (ip,))
    if row["n"] >= cfg["RESET_MAX_PER_IP"]:
        return True
    if user_id is not None:
        row = fetch_one("SELECT COUNT(*) AS n FROM password_reset_tokens "
                        "WHERE user_id = %s AND created_at > DATE_SUB(NOW(), INTERVAL 1 HOUR)", (user_id,))
        if row["n"] >= cfg["RESET_MAX_PER_ACCOUNT"]:
            return True
    return False


def _record_request(ip):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO password_reset_requests (ip_address) VALUES (%s)", (ip,))
        # keep the table small
        cursor.execute(
            "DELETE FROM password_reset_requests WHERE created_at < DATE_SUB(NOW(), INTERVAL 1 DAY)")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


# ----------------------------------------------------------- issuing

def _create_token(user_id, ip):
    """Invalidate older unused tokens, store the new token's hash, return the raw token."""
    token = secrets.token_urlsafe(32)
    minutes = current_app.config["PASSWORD_RESET_MINUTES"]
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE password_reset_tokens SET used_at = NOW() WHERE user_id = %s AND used_at IS NULL",
                       (user_id,))
        cursor.execute("INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, requested_ip) "
                       "VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL %s MINUTE), %s)",
                       (user_id, _hash(token), minutes, ip))
        db.commit()
        return token
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def _void_token(token):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE password_reset_tokens SET used_at = NOW() WHERE token_hash = %s", (_hash(token),))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        cursor.close()


def email_reset_link(user, ip, actor_id=None):
    """Create a token and email the reset link to the account's registered address.

    Raises MailNotConfigured / MailSendError. On send failure the token is voided, so a link that
    was never delivered cannot be used.
    """
    from flask import url_for
    token = _create_token(user["id"], ip)
    link = public_base_url() + url_for("auth.reset_password", token=token)
    subject, text, html = reset_email(
        link, current_app.config["PASSWORD_RESET_MINUTES"])
    try:
        send_mail(user["email"], subject, text, html)
    except (MailNotConfigured, MailSendError):
        _void_token(token)
        raise
    log_action(actor_id or user["id"], "password_reset_requested", "auth",
               "Password reset email sent" +
               (" by an administrator" if actor_id else ""),
               affected_record=f"user:{user['id']}")


def request_reset(email, ip):
    """Handle the public 'Forgot Password' form.

    Returns (status, None): status is 'unavailable' (email not configured on the server - the same
    for everybody, so it leaks nothing), 'rate_limited', or 'accepted'. 'accepted' is returned
    whether or not an account matched and never claims that an email was delivered.
    """
    if not recovery_available():
        return "unavailable"

    user = find_eligible_user(email)
    if _rate_limited(ip, user["id"] if user else None):
        _record_request(ip)
        return "rate_limited"
    _record_request(ip)

    if user is not None:
        try:
            email_reset_link(user, ip)
        except (MailNotConfigured, MailSendError):
            # Do not tell the visitor (that would reveal the account exists); record it for admins.
            log_action(user["id"], "password_reset_email_failed", "auth",
                       "Password reset email could not be sent (SMTP error)", affected_record=f"user:{user['id']}")
    else:
        log_action(None, "password_reset_unknown", "auth",
                   "Password reset requested for an ineligible address")
    return "accepted"


# ----------------------------------------------------------- redeeming

def get_valid_token(token):
    """Return the token row (with user info) if it is unused, unexpired and the account is active."""
    if not token or len(token) > 100:
        return None
    return fetch_one(
        "SELECT t.id, t.user_id, u.username FROM password_reset_tokens t JOIN users u ON u.id = t.user_id "
        "WHERE t.token_hash = %s AND t.used_at IS NULL AND t.expires_at > NOW() AND u.is_active = 1",
        (_hash(token),))


def complete_reset(token, new_password):
    """Change the password and burn the token in ONE transaction. Returns True on success."""
    row = get_valid_token(token)
    if row is None:
        return False
    db = get_db()
    cursor = db.cursor()
    try:
        # 'AND used_at IS NULL' + rowcount makes the token strictly single-use even under a race
        cursor.execute("UPDATE password_reset_tokens SET used_at = NOW() WHERE id = %s AND used_at IS NULL AND expires_at > NOW()",
                       (row["id"],))
        if cursor.rowcount != 1:
            db.rollback()
            return False
        cursor.execute("UPDATE users SET password_hash = %s, must_change_password = 0, "
                       "failed_login_attempts = 0, locked_until = NULL WHERE id = %s",
                       (generate_password_hash(new_password), row["user_id"]))
        cursor.execute("UPDATE password_reset_tokens SET used_at = NOW() WHERE user_id = %s AND used_at IS NULL",
                       (row["user_id"],))
        log_action(row["user_id"], "password_reset_completed", "auth", "Password reset using an emailed link",
                   affected_record=f"user:{row['user_id']}", commit=False)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
