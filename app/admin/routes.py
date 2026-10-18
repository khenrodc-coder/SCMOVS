import mysql.connector
from typing import Any, cast

from flask import (Blueprint, abort, flash, g, jsonify, redirect,
                   render_template, request, url_for)
from werkzeug.security import generate_password_hash

from app.admin import services
from app.auth import recovery
from app.auth.decorators import permission_required, role_required
from app.mailer import MailNotConfigured, MailSendError
from app.modal_utils import json_errors, json_ok, wants_json
from app.validators import build_full_name, clean, normalize_email
from app.auth.services import is_safe_next, validate_new_password

admin_bp = Blueprint("admin", __name__, url_prefix="/super-admin")


def users_admin_required(view):
    """Server-side checks for every user-management route:
    logged in -> role is super_admin -> holds the users.manage permission."""
    return role_required("super_admin")(permission_required("users.manage")(view))


def _back_to_list():
    target = request.form.get("next", "")
    if is_safe_next(target):
        return redirect(target)
    return redirect(url_for("admin.users_list"))


def _get_user_or_404(user_id):
    user = services.get_user(user_id)
    if user is None:
        abort(404)
    return cast(Any, user)


# ------------------------------------------------------------------ list

@admin_bp.route("/users")
@users_admin_required
def users_list():
    data = services.list_users(request.args)

    # Links for the sortable column headers (keep current search and filters)
    sort_urls = {}
    for column in services.SORT_COLUMNS:
        next_dir = "desc" if (
            data["sort"] == column and data["direction"] == "asc") else "asc"
        sort_urls[column] = url_for(
            "admin.users_list", **data["base_filters"], sort=column, dir=next_dir)

    filters = dict(data["base_filters"], sort=data["sort"],
                   dir=data["direction"])
    return render_template("super_admin/users/list.html", sort_urls=sort_urls, filters=filters, **data)


# ---------------------------------------------------------------- create

def _read_user_form(with_username):
    form = {k: clean(request.form.get(k)) for k in ("first_name", "middle_name", "last_name")}
    form["email"] = normalize_email(request.form.get("email"))
    form["role"] = request.form.get("role", "").strip()
    if with_username:
        form["username"] = request.form.get("username", "").strip()
    form["full_name"] = build_full_name(form["first_name"], form["middle_name"], form["last_name"])
    return form


@admin_bp.route("/users/new", methods=["GET", "POST"])
@users_admin_required
def user_create():
    """GET returns the modal's HTML; POST (fetch) returns JSON."""
    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("admin.users_list"))
        return render_template("super_admin/users/_form_modal.html", mode="create", form={}, target=None,
                               editing_self=False, role_options=_role_choices(services.NEW_USER_ROLES))

    form = _read_user_form(with_username=True)
    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")

    errors = services.validate_user_fields(form, services.NEW_USER_ROLES)
    password_error = validate_new_password(password)
    if password_error:
        errors["password"] = password_error
    elif password != confirm:
        errors["confirm_password"] = "The passwords do not match."
    if errors:
        return json_errors(errors)

    try:
        services.create_user(form, generate_password_hash(password), g.user["id"])
    except mysql.connector.IntegrityError:
        # Two people saved the same username/email at the same moment
        return json_errors({"username": "That username or email address is already in use."})
    return json_ok(f"Account '{form['username']}' was created. They must change the password at first login.")


# ------------------------------------------------------------------ edit

@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@users_admin_required
def user_edit(user_id):
    user = _get_user_or_404(user_id)
    editing_self = user["id"] == g.user["id"]
    allowed = list(services.allowed_roles_for(user["has_student"]))

    # Show the current role in the dropdown even if it is outside the normal rules
    display_names = list(allowed)
    if user["role"] not in display_names:
        display_names.append(user["role"])

    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("admin.users_list"))
        return render_template("super_admin/users/_form_modal.html", mode="edit", form=user, target=user,
                               editing_self=editing_self, role_options=_role_choices(display_names))

    form = _read_user_form(with_username=False)
    if editing_self:
        form["role"] = str(user["role"])                 # nobody can change their own role
    role_changed = form["role"] != user["role"]

    errors = services.validate_user_fields(form, allowed, user_id=user["id"], check_role=role_changed,
                                           student_number=user["student_number"])
    if (role_changed and not errors and user["active_assignments"] and form["role"] != "council_officer"):
        errors["role"] = "This officer has an active council assignment. End the assignment before changing the role."
    if errors:
        return json_errors(errors)

    try:
        services.update_user(user, form, g.user["id"])
    except mysql.connector.IntegrityError:
        return json_errors({"email": "That email address is already in use."})
    return json_ok(f"Account '{user['username']}' was updated.")


def _role_choices(names):
    icons = {"super_admin": "fa-shield-halved", "school_admin": "fa-school", "council_officer": "fa-user-tie",
             "student": "fa-graduation-cap"}
    return [(r["name"], r["display_name"], icons.get(r["name"], "fa-user")) for r in services.roles_for(names)]


# ------------------------------------------------------ activate / deactivate

@admin_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@users_admin_required
def user_toggle_active(user_id):
    user = _get_user_or_404(user_id)
    if user["id"] == g.user["id"]:
        flash("You cannot deactivate your own account.", "error")
        return _back_to_list()

    make_active = not user["is_active"]
    services.set_user_active(user, make_active, g.user["id"])
    flash(
        f"Account '{user['username']}' was {'activated' if make_active else 'deactivated'}.", "success")
    return _back_to_list()


# --------------------------------------------------------- reset password

@admin_bp.route("/users/<int:user_id>/reset-password", methods=["GET", "POST"])
@users_admin_required
def user_reset_password(user_id):
    """Modal with two ways to reset: email a one-time link (preferred) or issue a one-time temporary password."""
    user = _get_user_or_404(user_id)
    if user["id"] == g.user["id"]:
        if request.method == "GET" and wants_json():
            return render_template("super_admin/users/_reset_modal.html", target=user, blocked=True,
                                   can_email=False, masked="")
        return json_errors({"_form": "Use your Profile page to change your own password."})

    can_email = bool(user["email"]) and recovery.recovery_available()

    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("admin.users_list"))
        return render_template("super_admin/users/_reset_modal.html", target=user, blocked=False,
                               can_email=can_email, masked=_mask_email(user["email"]))

    method = request.form.get("method", "")
    if method == "email":
        if not can_email:
            return json_errors({"_form": "Email reset is not available: the account has no email or SMTP is not configured."})
        try:
            recovery.email_reset_link(user, request.remote_addr or "unknown", actor_id=g.user["id"])
        except (MailNotConfigured, MailSendError):
            return json_errors({"_form": "The email could not be sent. Check the SMTP settings, then try again."}, status=502)
        return json_ok(f"A password reset link was emailed to {_mask_email(user['email'])}.")

    if method == "temp":
        temp_password = services.generate_temp_password()
        services.reset_user_password(user, generate_password_hash(temp_password), g.user["id"])
        html = render_template("super_admin/users/_reset_result.html", target=user, temp_password=temp_password)
        response = jsonify(ok=True, message="Temporary password created.", html_result=html)
        response.headers["Cache-Control"] = "no-store"
        return response

    return json_errors({"_form": "Please choose how to reset the password."})


def _mask_email(email):
    if not email or "@" not in email:
        return ""
    local, _, domain = email.partition("@")
    return (local[:2] + "***@" + domain) if len(local) > 2 else ("***@" + domain)
