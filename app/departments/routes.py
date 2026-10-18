import mysql.connector
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.decorators import access_required
from app.departments import services
from app.modal_utils import json_errors, json_ok, wants_json

departments_bp = Blueprint("departments", __name__, url_prefix="/departments")

# Super Admin only (the seed gives departments.manage to no other role)
manage = access_required(("super_admin",), "departments.manage")


def _read_form():
    return {"name": request.form.get("name", "").strip(),
            "code": request.form.get("code", "").strip().upper()}


def _get_or_404(department_id):
    department = services.get_department(department_id)
    if department is None:
        abort(404)
    return department


@departments_bp.route("")
@manage
def list_page():
    return render_template("departments/list.html", departments=services.list_departments())


@departments_bp.route("/new", methods=["GET", "POST"])
@manage
def create():
    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("departments.list_page"))
        return render_template("departments/_form_modal.html", mode="create", form={"name": "", "code": ""}, department=None)
    form = _read_form()
    errors = services.validate_department(form)
    if errors:
        return json_errors(errors)
    try:
        services.create_department(form, g.user["id"])
    except mysql.connector.IntegrityError:
        return json_errors({"name": "That name or code is already used."})
    return json_ok(f"Department '{form['name']}' was created.")


@departments_bp.route("/<int:department_id>/edit", methods=["GET", "POST"])
@manage
def edit(department_id):
    department = _get_or_404(department_id)
    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("departments.list_page"))
        return render_template("departments/_form_modal.html", mode="edit", department=department,
                               form={"name": department["name"], "code": department["code"]})
    form = _read_form()
    errors = services.validate_department(form, department_id)
    if errors:
        return json_errors(errors)
    try:
        services.update_department(department, form, g.user["id"])
    except mysql.connector.IntegrityError:
        return json_errors({"name": "That name or code is already used."})
    return json_ok(f"Department '{form['name']}' was updated.")


@departments_bp.route("/<int:department_id>/toggle-active", methods=["POST"])
@manage
def toggle_active(department_id):
    department = _get_or_404(department_id)
    make_active = not department["is_active"]
    error = services.set_department_active(department, make_active, g.user["id"])
    if error:
        flash(error, "error")
    else:
        flash(f"Department '{department['name']}' was {'activated' if make_active else 'deactivated'}.", "success")
    return redirect(url_for("departments.list_page"))
