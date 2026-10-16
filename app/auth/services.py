import time
from typing import Any, cast

from flask import flash, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.audit.services import log_action
from app.db import fetch_all, fetch_one, get_db

DEFAULT_LOCKOUT_MINUTES = 15          # used when the setting is missing
GENERIC_LOGIN_ERROR = "Invalid Credentials."

# Checked when the username does not exist, so the response time looks the same
DUMMY_HASH = generate_password_hash("not-a-real-password")


def get_setting_int(key, default):
    """Read a whole-number setting from system_settings, with a safe fallback."""
    row = cast(dict[str, Any] | None, fetch_one(
        "SELECT setting_value FROM system_settings WHERE setting_key = %s", (key,)))
    if row is None:
        return default

    value = row.get("setting_value")
    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def is_safe_next(target):
    """Only allow redirects to paths on this site (blocks open-redirect attacks)."""
    return bool(target) and target.startswith("/") and not target.startswith("//") and "\\" not in target


# ---------------------------------------------------------------- login

def _find_user_for_login(username):
    return fetch_one(
        "SELECT u.id, u.password_hash, u.is_active, "
        "       (u.locked_until IS NOT NULL AND u.locked_until > NOW()) AS is_locked "
        "FROM users u WHERE u.username = %s",
        (username,),
    )


def _record_failed_login(user_id, max_attempts):
    """Count the failure. On reaching the limit, lock the account and reset the counter."""
    lockout_minutes = get_setting_int(
        "lockout_minutes", DEFAULT_LOCKOUT_MINUTES)
    db = get_db()
    cursor = db.cursor()
    try:
        # MySQL evaluates SET assignments left to right, so locked_until is
        # calculated from the OLD counter before the counter is changed.
        cursor.execute(
            "UPDATE users SET "
            "locked_until = IF(failed_login_attempts + 1 >= %s, DATE_ADD(NOW(), INTERVAL %s MINUTE), locked_until), "
            "failed_login_attempts = IF(failed_login_attempts + 1 >= %s, 0, failed_login_attempts + 1) "
            "WHERE id = %s",
            (max_attempts, lockout_minutes, max_attempts, user_id),
        )
        log_action(user_id, "login_failed", "auth", "Failed login attempt",
                   affected_record=f"user:{user_id}", commit=False)
        row = cast(dict[str, Any] | None, fetch_one(
            "SELECT (locked_until IS NOT NULL AND locked_until > NOW()) AS locked "
            "FROM users WHERE id = %s",
            (user_id,),
        ))
        if row and row.get("locked"):
            log_action(user_id, "account_locked", "auth",
                       f"Account locked for {lockout_minutes} minutes after too many failed logins",
                       affected_record=f"user:{user_id}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def _record_successful_login(user_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE users SET failed_login_attempts = 0, locked_until = NULL, last_login_at = NOW() "
            "WHERE id = %s",
            (user_id,),
        )
        log_action(user_id, "login", "auth", "User logged in",
                   affected_record=f"user:{user_id}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def attempt_login(username, password):
    """Return (user_id, None) on success or (None, error_message) on failure."""
    max_attempts = get_setting_int("max_failed_logins", 5)
    user = cast(dict[str, Any] | None, _find_user_for_login(username))

    if user is None:
        check_password_hash(DUMMY_HASH, password)
        log_action(None, "login_failed", "auth",
                   "Failed login attempt for an unknown account")
        return None, GENERIC_LOGIN_ERROR

    if user["is_locked"]:
        return None, "This account is temporarily locked. Please try again in a few minutes."

    if not check_password_hash(user["password_hash"], password):
        _record_failed_login(user["id"], max_attempts)
        return None, GENERIC_LOGIN_ERROR

    if not user["is_active"]:
        log_action(user["id"], "login_blocked", "auth", "Login attempt on an inactive account",
                   affected_record=f"user:{user['id']}")
        return None, "This account is inactive. Please contact the school administration."

    user_id = cast(int, user["id"])
    _record_successful_login(user_id)
    return user_id, None


# ---------------------------------------------------- per-request user

def load_current_user():
    """Runs before every request. Loads the user and role fresh from MySQL.

    Because the role is read from the database each time, role changes
    (for example a student elected as an officer) and deactivations take
    effect on the very next request.
    """
    g.user = None
    g.permissions = None

    if request.endpoint == "static":
        return None

    user_id = session.get("user_id")
    if user_id is None:
        return None

    user = cast(dict[str, Any] | None, fetch_one(
        "SELECT u.id, u.username, u.email, u.full_name, u.is_active, u.must_change_password, "
        "       r.name AS role, r.display_name AS role_display "
        "FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = %s",
        (user_id,),
    ))
    if user is None or not user["is_active"]:
        session.clear()
        return None

    # Idle timeout (Settings -> Security). "last_seen" is refreshed on every request.
    timeout_minutes = get_setting_int("session_timeout_minutes", 30)
    now = int(time.time())
    last_seen = session.get("last_seen")
    if isinstance(last_seen, int) and now - last_seen > timeout_minutes * 60:
        session.clear()
        flash("Your session expired because of inactivity. Please log in again.", "warning")
        return None
    session["last_seen"] = now

    g.user = user

    # Force a password change before anything else
    if user["must_change_password"] and request.endpoint not in ("auth.change_password", "auth.logout"):
        flash("You must change your password before continuing.", "warning")
        return redirect(url_for("auth.change_password"))
    return None


# ------------------------------------------------------------ permissions

def get_permissions():
    """Set of permission codes for the current user's role (loaded once per request)."""
    if g.get("permissions") is None:
        if g.get("user") is None:
            g.permissions = set()
        else:
            rows = cast(list[dict[str, Any]], fetch_all(
                "SELECT p.code FROM permissions p "
                "JOIN role_permissions rp ON rp.permission_id = p.id "
                "JOIN roles r ON r.id = rp.role_id WHERE r.name = %s",
                (g.user["role"],),
            ))
            g.permissions = {cast(str, row["code"]) for row in rows}
    return g.permissions


def has_permission(code):
    return code in get_permissions()


# --------------------------------------------------------------- passwords

def validate_new_password(password):
    """Return an error message, or None if the password is acceptable."""
    min_length = get_setting_int("password_min_length", 8)
    if len(password) < min_length:
        return f"Password must be at least {min_length} characters long."
    if len(password) > 128:
        return "Password must be 128 characters or fewer."
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        return "Password must contain at least one letter and one number."
    return None
