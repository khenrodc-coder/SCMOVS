from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.audit.services import log_action
from app.auth.decorators import login_required
from app.auth import recovery
from app.auth.services import attempt_login, get_setting_int, is_safe_next, validate_new_password
from app.validators import normalize_email, validate_email_format
from app.db import fetch_one, get_db

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("dashboard.home"))

    next_url = request.form.get("next") or request.args.get("next", "")

    if request.method == "POST":
        username = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Please enter both your username and password.", "error")
        elif len(username) > 50 or len(password) > 128:
            flash("Invalid username or password.", "error")
        else:
            user_id, error = attempt_login(username, password)
            if error:
                flash(error, "error")
            else:
                session.clear()              # new session on login (prevents session fixation)
                session["user_id"] = user_id
                session.permanent = True     # uses PERMANENT_SESSION_LIFETIME
                if is_safe_next(next_url):
                    return redirect(next_url)
                return redirect(url_for("dashboard.home"))

    return render_template("auth/login.html", next_url=next_url, recovery_enabled=recovery.recovery_available())


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    log_action(g.user["id"], "logout", "auth", "User logged out",
               affected_record=f"user:{g.user['id']}")
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    min_length = get_setting_int("password_min_length", 8)

    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        row = fetch_one(
            "SELECT password_hash FROM users WHERE id = %s", (g.user["id"],))
        password_hash = None
        if row is not None:
            getter = getattr(row, "get", None)
            if callable(getter):
                password_hash = getter("password_hash")
            else:
                password_hash = getattr(row, "password_hash", None)
        problem = validate_new_password(
            new) if new else "Please enter a new password."

        if not isinstance(password_hash, str):
            flash("Unable to verify your account at this time.", "error")
            return render_template("auth/change_password.html", min_length=min_length)
        elif not check_password_hash(password_hash, current):
            flash("Your current password is incorrect.", "error")
        elif new != confirm:
            flash("The new passwords do not match.", "error")
        elif new == current:
            flash("The new password must be different from the current one.", "error")
        elif problem:
            flash(problem, "error")
        else:
            db = get_db()
            cursor = db.cursor()
            try:
                cursor.execute(
                    "UPDATE users SET password_hash = %s, must_change_password = 0 WHERE id = %s",
                    (generate_password_hash(new), g.user["id"]),
                )
                log_action(g.user["id"], "password_changed", "auth", "User changed their own password",
                           affected_record=f"user:{g.user['id']}", commit=False)
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                cursor.close()
            flash("Your password was changed successfully.", "success")
            return redirect(url_for("dashboard.home"))

    return render_template("auth/change_password.html", min_length=min_length)


# ------------------------------------------------------------ forgot / reset password

GENERIC_RESET_MESSAGE = ("If an eligible account exists, password reset instructions will be sent "
                         "to its registered email address.")


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Login-page modal. GET returns the modal HTML; POST answers JSON (CSRF-protected via X-CSRFToken)."""
    if request.method == "GET":
        if request.headers.get("X-Requested-With") != "fetch":
            return redirect(url_for("auth.login"))
        return render_template("auth/_forgot_modal.html")
    if g.user is not None:
        return jsonify(ok=False, message="You are already signed in."), 400
    email = normalize_email(request.form.get("email", ""))
    problem = validate_email_format(email)
    if problem:
        return jsonify(ok=False, message=problem, errors={"email": problem}), 422

    status = recovery.request_reset(email, request.remote_addr or "unknown")
    if status == "unavailable":
        return jsonify(ok=False, message="Password recovery by email is not available right now. "
                                         "Please contact the school administration."), 503
    if status == "rate_limited":
        return jsonify(ok=False, message="Too many reset requests. Please wait a few minutes and try again."), 429
    return jsonify(ok=True, message=GENERIC_RESET_MESSAGE)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    row = recovery.get_valid_token(token)
    if row is None:
        # one message for invalid, expired and already-used links: nothing about the token is revealed
        return render_template("auth/reset_password.html", valid=False, min_length=get_setting_int("password_min_length", 8)), 400

    error = None
    if request.method == "POST":
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        error = validate_new_password(new) if new else "Please enter a new password."
        if error is None and new != confirm:
            error = "The two passwords do not match."
        if error is None:
            if recovery.complete_reset(token, new):
                return render_template("auth/reset_password.html", valid=True, done=True,
                                       min_length=get_setting_int("password_min_length", 8))
            return render_template("auth/reset_password.html", valid=False,
                                   min_length=get_setting_int("password_min_length", 8)), 400
    return render_template("auth/reset_password.html", valid=True, done=False, error=error,
                           min_length=get_setting_int("password_min_length", 8))
