import mysql.connector
from typing import Any, cast

from flask import (Blueprint, abort, flash, g, make_response, redirect,
                   render_template, request, url_for)
from werkzeug.security import generate_password_hash

from app.admin import services
from app.auth.decorators import permission_required, role_required
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

@admin_bp.route("/users/new", methods=["GET", "POST"])
@users_admin_required
def user_create():
    form = {"username": "", "full_name": "", "email": "", "role": ""}
    errors = []

    if request.method == "POST":
        form = {key: request.form.get(key, "").strip() for key in form}
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = services.validate_user_fields(form, services.NEW_USER_ROLES)
        password_error = validate_new_password(password)
        if password_error:
            errors.append(password_error)
        elif password != confirm:
            errors.append("The passwords do not match.")

        if not errors:
            try:
                services.create_user(
                    form, generate_password_hash(password), g.user["id"])
            except mysql.connector.IntegrityError:
                # Two people saved the same username/email at the same moment
                errors.append(
                    "That username or email address is already in use.")
            else:
                flash(f"Account '{form['username']}' was created. They must change the password at first login.",
                      "success")
                return redirect(url_for("admin.users_list"))

    return render_template(
        "super_admin/users/form.html", mode="create", form=form, errors=errors,
        role_options=services.roles_for(services.NEW_USER_ROLES),
        editing_self=False, target=None,
    )


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

    # NOTE: this must stay OUTSIDE the "if" above, so it always exists
    form = {"full_name": user["full_name"],
            "email": user["email"] or "", "role": user["role"]}
    errors = []

    if request.method == "POST":
        form = {key: request.form.get(key, "").strip() for key in form}
        if editing_self:
            # nobody can change their own role
            form["role"] = str(user["role"])
        role_changed = form["role"] != user["role"]

        errors = services.validate_user_fields(
            form, allowed, user_id=user["id"], check_role=role_changed)
        if (role_changed and not errors and user["active_assignments"]
                and form["role"] != "council_officer"):
            errors.append(
                "This officer has an active council assignment. End the assignment before changing the role.")

        if not errors:
            try:
                services.update_user(user, form, g.user["id"])
            except mysql.connector.IntegrityError:
                errors.append("That email address is already in use.")
            else:
                flash(f"Account '{user['username']}' was updated.", "success")
                return redirect(url_for("admin.users_list"))

    return render_template(
        "super_admin/users/form.html", mode="edit", form=form, errors=errors,
        role_options=services.roles_for(display_names),
        editing_self=editing_self, target=user,
    )


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

@admin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@users_admin_required
def user_reset_password(user_id):
    user = _get_user_or_404(user_id)
    if user["id"] == g.user["id"]:
        flash("Use 'Change Password' to change your own password.", "error")
        return _back_to_list()

    temp_password = services.generate_temp_password()
    services.reset_user_password(
        user, generate_password_hash(temp_password), g.user["id"])

    # The temporary password is shown ONCE, on this response only (not stored anywhere readable)
    response = make_response(render_template(
        "super_admin/users/password_reset.html", target=user, temp_password=temp_password))
    response.headers["Cache-Control"] = "no-store"
    return response
