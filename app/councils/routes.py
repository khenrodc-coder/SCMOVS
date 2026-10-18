from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from app.modal_utils import json_error_list, json_ok, json_redirect, json_reload, modal_notice, wants_json

from app.auth.decorators import access_required
from app.councils import services

councils_bp = Blueprint("councils", __name__, url_prefix="/councils")

# School Admin and Super Admin both hold councils.manage in the seed
manage = access_required(("super_admin", "school_admin"), "councils.manage")

FORM_FIELDS = ("name", "department_id", "school_year_id",
               "election_id", "term_start", "term_end")
ACTION_DONE = {"complete": "completed",
               "archive": "archived", "restore": "restored"}


def _read_form():
    return {key: request.form.get(key, "").strip() for key in FORM_FIELDS}


def _get_or_404(council_id):
    council = services.get_council(council_id)
    if council is None:
        abort(404)
    return council


def _get_officer_or_404(council, officer_id):
    officer = services.get_officer(officer_id)
    # an officer of ANOTHER council is not found
    if officer is None or officer["council_id"] != council["id"]:
        abort(404)
    return officer


def _form_fragment(mode, form, council=None, locked=False):
    departments, years, elections = services.get_form_options(council)
    return render_template("councils/_form_modal.html", mode=mode, form=form, council=council, locked=locked,
                           departments=departments, school_years=years, elections=elections)


# ------------------------------------------------------------------ list

@councils_bp.route("")
@manage
def list_page():
    data = services.list_councils(request.args)
    return render_template("councils/list.html", filters=data["base_filters"],
                           options=services.get_filter_options(), statuses=services.STATUSES, **data)


# ---------------------------------------------------------------- create

@councils_bp.route("/new", methods=["GET", "POST"])
@manage
def create():
    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("councils.list_page"))
        return _form_fragment("create", {key: "" for key in FORM_FIELDS})
    form = _read_form()
    errors = services.validate_council(form)
    if errors:
        return json_error_list(errors)
    council_id = services.create_council(form, g.user["id"])
    return json_redirect(f"Council '{form['name']}' was created. Now assign its officers.",
                         url_for("councils.detail", council_id=council_id))


# ---------------------------------------------------------------- detail

@councils_bp.route("/<int:council_id>")
@manage
def detail(council_id):
    council = _get_or_404(council_id)
    active, past = services.get_officers(council_id)
    return render_template("councils/detail.html", council=council, active_officers=active, past_officers=past,
                           positions=services.get_positions_for_assignment(council_id), actions=services.ACTIONS)


# ------------------------------------------------------------------ edit

@councils_bp.route("/<int:council_id>/edit", methods=["GET", "POST"])
@manage
def edit(council_id):
    council = _get_or_404(council_id)
    if council["status"] != "active":
        message = "Only an active council can be edited."
        if wants_json():
            return modal_notice(message, "Council can't be edited") if request.method == "GET" else json_error_list([message], 409)
        flash(message, "error")
        return redirect(url_for("councils.detail", council_id=council_id))
    if request.method == "GET" and not wants_json():
        return redirect(url_for("councils.detail", council_id=council_id))

    # department and school year decide who can be an officer
    locked = council["officer_rows"] > 0
    if request.method == "GET":
        form = {"name": council["name"], "department_id": str(council["department_id"]),
                "school_year_id": str(council["school_year_id"]),
                "election_id": str(council["election_id"] or ""),
                "term_start": str(council["term_start"]), "term_end": str(council["term_end"])}
        return _form_fragment("edit", form, council, locked)

    form = _read_form()
    if locked:
        form["department_id"] = str(council["department_id"])
        form["school_year_id"] = str(council["school_year_id"])
    errors = services.validate_council(form, council, locked)
    if errors:
        return json_error_list(errors)
    services.update_council(council, form, g.user["id"])
    return json_reload(f"Council '{form['name']}' was updated.")


# ----------------------------------------------------------- status change

@councils_bp.route("/<int:council_id>/status/<action>", methods=["POST"])
@manage
def change_status(council_id, action):
    if action not in services.ACTIONS:
        abort(404)
    council = _get_or_404(council_id)
    error = services.change_status(council, action, g.user["id"])
    if error:
        flash(error, "error")
    else:
        flash(
            f"Council '{council['name']}' was {ACTION_DONE[action]}.", "success")
    return redirect(url_for("councils.detail", council_id=council_id))


# ---------------------------------------------------------------- officers

@councils_bp.route("/<int:council_id>/officers/add", methods=["POST"])
@manage
def add_officer(council_id):
    council = _get_or_404(council_id)
    number = request.form.get("student_number", "").strip()
    try:
        position_id = int(request.form.get("position_id", ""))
    except ValueError:
        position_id = None

    student, problem = services.find_student_for_council(council, number)
    if problem is None:
        problem = services.assign_officer(
            council, student, position_id, g.user["id"])
    if problem:
        flash(problem, "error")
    else:
        flash(
            f"{student['first_name']} {student['last_name']} is now an officer of this council.", "success")
    return redirect(url_for("councils.detail", council_id=council_id))


@councils_bp.route("/<int:council_id>/officers/<int:officer_id>/position", methods=["POST"])
@manage
def change_position(council_id, officer_id):
    council = _get_or_404(council_id)
    officer = _get_officer_or_404(council, officer_id)
    try:
        position_id = int(request.form.get("position_id", ""))
    except ValueError:
        position_id = None
    problem = services.change_position(
        council, officer, position_id, g.user["id"])
    flash(problem or "The position was changed.",
          "error" if problem else "success")
    return redirect(url_for("councils.detail", council_id=council_id))


@councils_bp.route("/<int:council_id>/officers/<int:officer_id>/remove", methods=["POST"])
@manage
def remove_officer(council_id, officer_id):
    council = _get_or_404(council_id)
    officer = _get_officer_or_404(council, officer_id)
    reason = request.form.get("reason", "").strip()[:200]
    problem = services.remove_officer(council, officer, reason, g.user["id"])
    flash(problem or f"{officer['full_name']} was removed from the council.",
          "error" if problem else "success")
    return redirect(url_for("councils.detail", council_id=council_id))
