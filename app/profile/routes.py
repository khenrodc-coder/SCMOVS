"""My Profile: personal details, profile photo, and change password (one sidebar entry: Profile)."""
import mysql.connector
from flask import Blueprint, abort, g, jsonify, render_template, request
from werkzeug.security import check_password_hash, generate_password_hash

from app import media
from app.audit.services import log_action
from app.auth.decorators import login_required
from app.auth.services import get_setting_int, validate_new_password
from app.db import fetch_one, get_db
from app.modal_utils import json_errors, json_ok
from app.validators import (build_full_name, clean, format_address, normalize_email, read_personal, validate_email_format,
                            validate_names, validate_personal)

profile_bp = Blueprint("profile", __name__, url_prefix="/profile")

# People whose personal record is managed by an administrator cannot edit it themselves.
SELF_EDIT_ROLES = ("super_admin", "school_admin")


def load_profile(user_id):
    return fetch_one(
        "SELECT u.id, u.username, u.email, u.full_name, u.first_name, u.middle_name, u.last_name, u.photo_path, "
        "       u.barangay, u.purok_street, u.city_municipality, u.province, u.contact_number, "
        "       DATE_FORMAT(u.birthdate, '%Y-%m-%d') AS birthdate, DATE_FORMAT(u.birthdate, '%M %e, %Y') AS birthdate_text, "
        "       r.name AS role, r.display_name AS role_display, "
        "       s.student_number, d.name AS department "
        "FROM users u JOIN roles r ON r.id = u.role_id "
        "LEFT JOIN students s ON s.user_id = u.id LEFT JOIN departments d ON d.id = s.department_id "
        "WHERE u.id = %s", (user_id,))


def can_edit_profile(profile):
    return profile["role"] in SELF_EDIT_ROLES and profile["student_number"] is None


# ------------------------------------------------------------------ page

@profile_bp.route("")
@login_required
def page():
    profile = load_profile(g.user["id"])
    return render_template("profile.html", profile=profile, address=format_address(profile), can_edit=can_edit_profile(profile),
                           min_length=get_setting_int("password_min_length", 8))


# ----------------------------------------------------------------- photo

@profile_bp.route("/photo", methods=["POST"])
@login_required
def upload_photo():
    """Only ever changes the logged-in user's own photo (the id comes from the session, not the form)."""
    path, error = media.save_image(request.files.get("photo"), "profiles")
    if error:
        return json_errors({"photo": error}, error)
    old = g.user["photo_path"]
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE users SET photo_path = %s WHERE id = %s", (path, g.user["id"]))
        log_action(g.user["id"], "profile_photo_changed", "profile", "Changed profile photo",
                   affected_record=f"user:{g.user['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        media.delete_image(path)               # the old photo stays: the database still points at it
        raise
    finally:
        cursor.close()
    media.delete_image(old)                    # only after the new one is safely saved
    return json_ok("Profile photo updated.", photo_url=media.photo_url(path))


@profile_bp.route("/photo/remove", methods=["POST"])
@login_required
def remove_photo():
    old = g.user["photo_path"]
    if not old:
        return json_errors({"photo": "You have no profile photo to remove."}, "You have no profile photo to remove.")
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE users SET photo_path = NULL WHERE id = %s", (g.user["id"],))
        log_action(g.user["id"], "profile_photo_removed", "profile", "Removed profile photo",
                   affected_record=f"user:{g.user['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
    media.delete_image(old)
    return json_ok("Profile photo removed.")


# ------------------------------------------------------------------ edit

@profile_bp.route("/edit", methods=["GET", "POST"])
@login_required
def edit():
    profile = load_profile(g.user["id"])
    if not can_edit_profile(profile):
        abort(403)
    if request.method == "GET":
        return render_template("profile/_edit_modal.html", profile=profile, form=profile, errors={})

    first, middle, last = (clean(request.form.get(k)) for k in ("first_name", "middle_name", "last_name"))
    email = normalize_email(request.form.get("email"))
    errors = validate_names(first, middle, last)
    personal = read_personal(request.form)
    errors.update(validate_personal(personal))
    problem = validate_email_format(email)
    if problem:
        errors["email"] = problem
    elif fetch_one("SELECT id FROM users WHERE email = %s AND id <> %s", (email, profile["id"])):
        errors["email"] = "That email address is already in use."
    if errors:
        return json_errors(errors)

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE users SET first_name = %s, middle_name = %s, last_name = %s, full_name = %s, email = %s, "
                       "barangay = %s, purok_street = %s, city_municipality = %s, birthdate = %s, contact_number = %s "
                       "WHERE id = %s", (first, middle or None, last, build_full_name(first, middle, last), email,
                                         personal["barangay"], personal["purok_street"], personal["city_municipality"],
                                         personal["birthdate"], personal["contact_number"], profile["id"]))
        log_action(g.user["id"], "profile_updated", "profile", "Updated own profile details",
                   affected_record=f"user:{profile['id']}", commit=False)
        db.commit()
    except mysql.connector.IntegrityError:
        db.rollback()
        return json_errors({"email": "That email address is already in use."})
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
    return json_ok("Profile updated.", reload=True)


# -------------------------------------------------------------- password

@profile_bp.route("/password", methods=["POST"])
@login_required
def change_password():
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    row = fetch_one("SELECT password_hash FROM users WHERE id = %s", (g.user["id"],))
    errors = {}
    if not current or row is None or not check_password_hash(row["password_hash"], current):
        errors["current_password"] = "Your current password is incorrect."
    problem = validate_new_password(new) if new else "Please enter a new password."
    if problem:
        errors["new_password"] = problem
    elif current and new == current:
        errors["new_password"] = "The new password must be different from the current one."
    if not errors and new != confirm:
        errors["confirm_password"] = "The new passwords do not match."
    if errors:
        return json_errors(errors)

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE users SET password_hash = %s, must_change_password = 0 WHERE id = %s",
                       (generate_password_hash(new), g.user["id"]))
        log_action(g.user["id"], "password_changed", "auth", "User changed their own password",
                   affected_record=f"user:{g.user['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
    return json_ok("Your password was changed successfully.")


# ----------------------------------------------------------------- theme (Super Admin only)

@profile_bp.route("/theme", methods=["POST"])
@login_required
def set_theme():
    """Dark mode is a Super Admin feature. The role is checked here on the server, not in the browser."""
    if g.user["role"] != "super_admin":
        abort(403)
    theme = request.form.get("theme", "")
    if theme not in ("light", "dark"):
        return json_errors({"theme": "Unknown theme."}, status=422)
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE users SET theme_preference = %s WHERE id = %s", (theme, g.user["id"]))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
    return json_ok("Theme saved.", theme=theme)
