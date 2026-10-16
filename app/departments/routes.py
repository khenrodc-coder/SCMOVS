import mysql.connector
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.decorators import access_required
from app.departments import services

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
    form, errors = {"name": "", "code": ""}, []
    if request.method == "POST":
        form = _read_form()
        errors = services.validate_department(form)
        if not errors:
            try:
                services.create_department(form, g.user["id"])
            except mysql.connector.IntegrityError:
                errors.append("That name or code is already used.")
            else:
                flash(f"Department '{form['name']}' was created.", "success")
                return redirect(url_for("departments.list_page"))
    return render_template("departments/form.html", mode="create", form=form, errors=errors, department=None)


@departments_bp.route("/<int:department_id>/edit", methods=["GET", "POST"])
@manage
def edit(department_id):
    department = _get_or_404(department_id)
    form, errors = {"name": department["name"], "code": department["code"]}, []
    if request.method == "POST":
        form = _read_form()
        errors = services.validate_department(form, department_id)
        if not errors:
            try:
                services.update_department(department, form, g.user["id"])
            except mysql.connector.IntegrityError:
                errors.append("That name or code is already used.")
            else:
                flash(f"Department '{form['name']}' was updated.", "success")
                return redirect(url_for("departments.list_page"))
    return render_template("departments/form.html", mode="edit", form=form, errors=errors, department=department)


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
