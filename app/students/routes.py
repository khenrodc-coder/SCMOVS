import mysql.connector
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from app.auth.decorators import access_required
from app.auth import recovery
from app.auth.services import is_safe_next
from app.mailer import MailNotConfigured, MailSendError
from app.modal_utils import json_errors, json_ok, wants_json
from app.validators import PERSONAL_FIELDS, clean, normalize_email, read_personal
from app.students import services

students_bp = Blueprint("students", __name__, url_prefix="/students")

# Super Admin and School Admin only. Each route ALSO needs the permission shown.
view_access = access_required(("super_admin", "school_admin"), "students.view")
manage_access = access_required(("super_admin", "school_admin"), "students.manage")

FORM_FIELDS = ("student_number", "first_name", "middle_name", "last_name", "email",
               "department_id", "year_level", "section", "school_year_id")

# Button text for each target status
STATUS_LABELS = {"active": "Activate", "inactive": "Deactivate", "graduated": "Mark graduated", "archived": "Archive"}
STATUS_DONE = {"active": "activated", "inactive": "deactivated", "graduated": "marked as graduated",
               "archived": "archived"}


def _read_form():
    form = {key: clean(request.form.get(key)) for key in FORM_FIELDS}
    form["student_number"] = request.form.get("student_number", "").strip()      # never altered: validated as typed
    form["email"] = normalize_email(request.form.get("email"))
    form["section"] = request.form.get("section", "").strip()
    form.update(read_personal(request.form))          # birthday, contact number, address
    return form


def _get_or_404(student_id):
    student = services.get_student(student_id)
    if student is None:
        abort(404)
    return student


def _form_fragment(mode, form, student=None):
    """HTML for the Add/Edit Student modal, with the dropdown data it needs."""
    departments = services.get_active_departments()
    years = services.get_assignable_school_years()
    if student is not None:
        # Keep the student's current department/school year selectable even if it is no longer active
        if not any(d["id"] == student["department_id"] for d in departments):
            from app.departments.services import get_department
            current = get_department(student["department_id"])
            departments.append({"id": current["id"], "name": current["name"] + " (inactive)", "code": ""})
        if not any(y["id"] == student["school_year_id"] for y in years):
            from app.school_years.services import get_school_year
            current = get_school_year(student["school_year_id"])
            years.append({"id": current["id"], "name": f"{current['name']} ({current['status']})", "status": current["status"]})
    return render_template("students/_form_modal.html", mode=mode, form=form, student=student,
                           departments=departments, school_years=years,
                           year_level_map=services.year_level_map(services.get_active_departments()))


def _back_to_list():
    target = request.form.get("next", "")
    return redirect(target if is_safe_next(target) else url_for("students.list_page"))


# ------------------------------------------------------------------ list

@students_bp.route("")
@view_access
def list_page():
    data = services.list_students(request.args)

    sort_urls = {}
    for column in services.SORT_COLUMNS:
        next_dir = "desc" if (data["sort"] == column and data["direction"] == "asc") else "asc"
        sort_urls[column] = url_for("students.list_page", **data["base_filters"], sort=column, dir=next_dir)
    filters = dict(data["base_filters"], sort=data["sort"], dir=data["direction"])

    return render_template("students/list.html", sort_urls=sort_urls, filters=filters,
                           options=services.get_filter_options(), transitions=services.STATUS_TRANSITIONS,
                           status_labels=STATUS_LABELS, **data)


# ---------------------------------------------------------------- create

@students_bp.route("/new", methods=["GET", "POST"])
@manage_access
def create():
    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("students.list_page"))
        return _form_fragment("create", {key: "" for key in FORM_FIELDS + PERSONAL_FIELDS})

    form = _read_form()
    errors = services.validate_student(form)
    if errors:
        return json_errors(errors)
    temp_password = services.generate_temp_password()
    try:
        services.create_student(form, generate_password_hash(temp_password), g.user["id"])
    except mysql.connector.IntegrityError:
        return json_errors({"student_number": "That Student ID or email already exists."})   # two admins saved at once
    # The temporary password is shown ONCE inside the modal. It is never stored readable or logged.
    html = render_template("students/_password_result.html", student_number=form["student_number"],
                           full_name=services.build_full_name(form), temp_password=temp_password, created=True)
    response = jsonify(ok=True, message=f"Student {form['student_number']} was created.", html_result=html)
    response.headers["Cache-Control"] = "no-store"
    return response


# ------------------------------------------------------------------ edit

@students_bp.route("/<int:student_id>/edit", methods=["GET", "POST"])
@manage_access
def edit(student_id):
    student = _get_or_404(student_id)
    locked = student["election_records"] > 0       # has voted or been a candidate
    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("students.list_page"))
        form = {"student_number": student["student_number"], "first_name": student["first_name"],
                "middle_name": student["middle_name"] or "", "last_name": student["last_name"],
                "email": student["email"] or "",
                "barangay": student["barangay"] or "", "purok_street": student["purok_street"] or "",
                "city_municipality": student["city_municipality"] or "", "birthdate": student["birthdate"] or "",
                "contact_number": student["contact_number"] or "",
                "department_id": str(student["department_id"]), "year_level": student["year_level"],
                "section": student["section"], "school_year_id": str(student["school_year_id"])}
        return _form_fragment("edit", form, student)

    form = _read_form()
    form["student_number"] = student["student_number"]          # the Student ID can never be changed here
    if locked:
        # Department and school year decide election eligibility, so they are frozen
        form["department_id"] = str(student["department_id"])
        form["school_year_id"] = str(student["school_year_id"])
    errors = services.validate_student(form, student)
    if errors:
        return json_errors(errors)
    try:
        services.update_student(student, form, g.user["id"])
    except mysql.connector.IntegrityError:
        return json_errors({"email": "That email address is already in use."})
    return json_ok(f"Student {student['student_number']} was updated.")


# ------------------------------------------------------- status change

@students_bp.route("/<int:student_id>/status", methods=["POST"])
@manage_access
def change_status(student_id):
    student = _get_or_404(student_id)
    new_status = request.form.get("status", "")
    error = services.change_status(student, new_status, g.user["id"])
    if error:
        flash(error, "error")
    else:
        flash(f"Student {student['student_number']} was {STATUS_DONE.get(new_status, 'updated')}.", "success")
    return _back_to_list()


# --------------------------------------------------------- reset password

@students_bp.route("/<int:student_id>/reset-password", methods=["GET", "POST"])
@manage_access
def reset_password(student_id):
    student = _get_or_404(student_id)
    # School Admin may only reset real student accounts (not an elected officer's account)
    if g.user["role"] != "super_admin" and student["user_role"] != "student":
        if request.method == "GET" and wants_json():
            return render_template("students/_reset_denied.html"), 403
        return json_errors({"_form": "Only a Super Admin can reset the password of a council officer."}, status=403)

    can_email = bool(student["email"]) and recovery.recovery_available()
    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("students.list_page"))
        masked = (student["email"][:2] + "***@" + student["email"].split("@", 1)[1]) if student["email"] else ""
        target = {"id": student["id"], "full_name": student["full_name"], "username": student["student_number"],
                  "email": student["email"]}
        return render_template("super_admin/users/_reset_modal.html", target=target, blocked=False, can_email=can_email,
                               masked=masked, action=url_for("students.reset_password", student_id=student_id))

    method = request.form.get("method", "")
    if method == "email":
        if not can_email:
            return json_errors({"_form": "Email reset is not available: no email on file, or SMTP is not configured."})
        try:
            recovery.email_reset_link({"id": student["user_id"], "email": student["email"]},
                                      request.remote_addr or "unknown", actor_id=g.user["id"])
        except (MailNotConfigured, MailSendError):
            return json_errors({"_form": "The email could not be sent. Check the SMTP settings, then try again."}, status=502)
        return json_ok("A password reset link was emailed to the student.")
    if method == "temp":
        temp_password = services.generate_temp_password()
        services.reset_student_password(student, generate_password_hash(temp_password), g.user["id"])
        html = render_template("students/_password_result.html", student_number=student["student_number"],
                               full_name=student["full_name"], temp_password=temp_password, created=False)
        response = jsonify(ok=True, message="Temporary password created.", html_result=html)
        response.headers["Cache-Control"] = "no-store"
        return response
    return json_errors({"_form": "Please choose how to reset the password."})
