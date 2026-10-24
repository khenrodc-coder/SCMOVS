from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.decorators import access_required
from app.elections import services
from app.modal_utils import json_error_list, json_ok, json_redirect, json_reload, modal_notice, wants_json

elections_bp = Blueprint("elections", __name__, url_prefix="/elections")

# Super Admin and School Admin only. Each route ALSO needs the permission shown.
view_access = access_required(
    ("super_admin", "school_admin"), "elections.view")
manage_access = access_required(
    ("super_admin", "school_admin"), "elections.manage")

FORM_FIELDS = ("name", "department_id", "school_year_id", "start_at", "end_at")
ACTION_DONE = {"schedule": "scheduled", "unschedule": "moved back to draft", "open": "opened for voting",
               "close": "closed", "archive": "archived", "restore": "restored"}


def _read_form():
    return {key: request.form.get(key, "").strip() for key in FORM_FIELDS}


def _get_or_404(election_id):
    election = services.get_election(election_id)
    if election is None:
        abort(404)
    return election


def _form_fragment(mode, form, election=None, locked=False):
    departments, years = services.get_form_options(election)
    return render_template("elections/_form_modal.html", mode=mode, form=form, election=election,
                           locked=locked, departments=departments, school_years=years)


# ------------------------------------------------------------------ list

@elections_bp.route("")
@view_access
def list_page():
    data = services.list_elections(request.args)
    return render_template("elections/list.html", filters=data["base_filters"],
                           options=services.get_filter_options(), statuses=services.STATUSES, **data)


# ---------------------------------------------------------------- create

@elections_bp.route("/new", methods=["GET", "POST"])
@manage_access
def create():
    """New Election modal. GET returns the HTML; POST (fetch) returns JSON."""
    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("elections.list_page"))
        return _form_fragment("create", {key: "" for key in FORM_FIELDS})
    form = _read_form()
    errors = services.validate_election(form)
    if errors:
        return json_error_list(errors)
    election_id = services.create_election(form, g.user["id"])
    return json_redirect(f"Election '{form['name']}' was created as a draft. Now add its positions.",
                         url_for("elections.detail", election_id=election_id))


# ---------------------------------------------------------------- detail

@elections_bp.route("/<int:election_id>")
@view_access
def detail(election_id):
    election = _get_or_404(election_id)
    editable = election["status"] in services.EDITABLE
    return render_template(
        "elections/detail.html", election=election, editable=editable,
        positions=services.get_election_positions(election_id),
        available_positions=services.get_available_positions(
            election_id) if editable else [],
        participation=services.get_participation(election_id),
        open_problem=services.open_problem(election),
        actions=services.ACTIONS)


# ------------------------------------------------------------------ edit

@elections_bp.route("/<int:election_id>/edit", methods=["GET", "POST"])
@manage_access
def edit(election_id):
    election = _get_or_404(election_id)
    if election["status"] not in services.EDITABLE:
        message = "Only draft or scheduled elections can be edited."
        if wants_json():
            return modal_notice(message, "Election can't be edited") if request.method == "GET" else json_error_list([message], 409)
        flash(message, "error")
        return redirect(url_for("elections.detail", election_id=election_id))
    if request.method == "GET" and not wants_json():
        return redirect(url_for("elections.detail", election_id=election_id))

    # department and school year decide who may be a candidate
    locked = election["candidate_count"] > 0
    if request.method == "GET":
        form = {"name": election["name"], "department_id": str(election["department_id"]),
                "school_year_id": str(election["school_year_id"]),
                "start_at": election["start_at"].strftime(services.DT_FORMAT),
                "end_at": election["end_at"].strftime(services.DT_FORMAT)}
        return _form_fragment("edit", form, election, locked)

    form = _read_form()
    if locked:
        form["department_id"] = str(election["department_id"])
        form["school_year_id"] = str(election["school_year_id"])
    errors = services.validate_election(form, locked=locked)
    if errors:
        return json_error_list(errors)
    services.update_election(election, form, g.user["id"])
    return json_reload(f"Election '{form['name']}' was updated.")


# ----------------------------------------------------------- status change

@elections_bp.route("/<int:election_id>/status/<action>", methods=["POST"])
@manage_access
def change_status(election_id, action):
    if action not in services.ACTIONS:
        abort(404)
    election = _get_or_404(election_id)
    error = services.change_status(election, action, g.user["id"])
    if error:
        flash(error, "error")
    else:
        flash(
            f"Election '{election['name']}' was {ACTION_DONE[action]}.", "success")
    return redirect(url_for("elections.detail", election_id=election_id))


# --------------------------------------------------------------- positions

@elections_bp.route("/<int:election_id>/positions/add", methods=["POST"])
@manage_access
def add_positions(election_id):
    election = _get_or_404(election_id)
    error = services.add_positions(
        election, request.form.getlist("position_ids"), g.user["id"])
    flash(error or "Positions were added.", "error" if error else "success")
    return redirect(url_for("elections.detail", election_id=election_id))


@elections_bp.route("/<int:election_id>/positions/<int:position_id>/remove", methods=["POST"])
@manage_access
def remove_position(election_id, position_id):
    election = _get_or_404(election_id)
    error = services.remove_position(election, position_id, g.user["id"])
    flash(error or "The position was removed.",
          "error" if error else "success")
    return redirect(url_for("elections.detail", election_id=election_id))


@elections_bp.route("/<int:election_id>/positions/<int:position_id>/move/<direction>", methods=["POST"])
@manage_access
def move_position(election_id, position_id, direction):
    if direction not in ("up", "down"):
        abort(404)
    election = _get_or_404(election_id)
    error = services.move_position(
        election, position_id, direction, g.user["id"])
    if error:
        flash(error, "error")
    return redirect(url_for("elections.detail", election_id=election_id))
