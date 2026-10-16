import mysql.connector
from flask import Blueprint, abort, flash, g, make_response, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from app.auth.decorators import access_required
from app.auth.services import is_safe_next
from app.students import services

students_bp = Blueprint("students", __name__, url_prefix="/students")

# Super Admin and School Admin only. Each route ALSO needs the permission shown.
view_access = access_required(("super_admin", "school_admin"), "students.view")
manage_access = access_required(("super_admin", "school_admin"), "students.manage")

FORM_FIELDS = ("student_number", "first_name", "middle_name", "last_name",
               "department_id", "year_level", "section", "school_year_id")

# Button text for each target status
STATUS_LABELS = {"active": "Activate", "inactive": "Deactivate", "graduated": "Mark graduated", "archived": "Archive"}
STATUS_DONE = {"active": "activated", "inactive": "deactivated", "graduated": "marked as graduated",
               "archived": "archived"}


def _read_form():
    return {key: request.form.get(key, "").strip() for key in FORM_FIELDS}


def _get_or_404(student_id):
    student = services.get_student(student_id)
    if student is None:
        abort(404)
    return student


def _form_page(mode, form, errors, student=None):
    """Render the create/edit form with the dropdown data it needs."""
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
    return render_template("students/form.html", mode=mode, form=form, errors=errors, student=student,
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
    form, errors = {key: "" for key in FORM_FIELDS}, []

    if request.method == "POST":
        form = _read_form()
        errors = services.validate_student(form)
        if not errors:
            temp_password = services.generate_temp_password()
            try:
                services.create_student(form, generate_password_hash(temp_password), g.user["id"])
            except mysql.connector.IntegrityError:
                errors.append("That Student ID already exists.")     # two admins saved the same ID at once
            else:
                # Shown ONCE on this response. It is never stored in readable form or in the audit log.
                response = make_response(render_template(
                    "students/password.html", student_number=form["student_number"],
                    full_name=services.build_full_name(form), temp_password=temp_password, created=True))
                response.headers["Cache-Control"] = "no-store"
                return response

    return _form_page("create", form, errors)


# ------------------------------------------------------------------ edit

@students_bp.route("/<int:student_id>/edit", methods=["GET", "POST"])
@manage_access
def edit(student_id):
    student = _get_or_404(student_id)
    locked = student["election_records"] > 0       # has voted or been a candidate
    form = {"student_number": student["student_number"], "first_name": student["first_name"],
            "middle_name": student["middle_name"] or "", "last_name": student["last_name"],
            "department_id": str(student["department_id"]), "year_level": student["year_level"],
            "section": student["section"], "school_year_id": str(student["school_year_id"])}
    errors = []

    if request.method == "POST":
        form = _read_form()
        form["student_number"] = student["student_number"]          # the Student ID can never be changed here
        if locked:
            # Department and school year decide election eligibility, so they are frozen
            form["department_id"] = str(student["department_id"])
            form["school_year_id"] = str(student["school_year_id"])
        errors = services.validate_student(form, student)
        if not errors:
            services.update_student(student, form, g.user["id"])
            flash(f"Student {student['student_number']} was updated.", "success")
            return redirect(url_for("students.list_page"))

    return _form_page("edit", form, errors, student)


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

@students_bp.route("/<int:student_id>/reset-password", methods=["POST"])
@manage_access
def reset_password(student_id):
    student = _get_or_404(student_id)
    # School Admin may only reset real student accounts (not an elected officer's account)
    if g.user["role"] != "super_admin" and student["user_role"] != "student":
        flash("Only a Super Admin can reset the password of a council officer.", "error")
        return _back_to_list()

    temp_password = services.generate_temp_password()
    services.reset_student_password(student, generate_password_hash(temp_password), g.user["id"])
    response = make_response(render_template(
        "students/password.html", student_number=student["student_number"], full_name=student["full_name"],
        temp_password=temp_password, created=False))
    response.headers["Cache-Control"] = "no-store"
    return response
