import mysql.connector
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.decorators import access_required
from app.auth.services import is_safe_next
from app.candidates import services
from app.utils import to_int

candidates_bp = Blueprint("candidates", __name__, url_prefix="/candidates")

# School Admin and Super Admin both hold candidates.manage in the seed
manage = access_required(("super_admin", "school_admin"), "candidates.manage")


def _get_or_404(candidate_id):
    candidate = services.get_candidate(candidate_id)
    if candidate is None:
        abort(404)
    return candidate


# ------------------------------------------------------------------ list

@candidates_bp.route("")
@manage
def list_page():
    data = services.list_candidates(request.args)
    return render_template("candidates/list.html", filters=data["base_filters"],
                           options=services.get_filter_options(), statuses=services.STATUSES, **data)


# -------------------------------------------------------------- register

@candidates_bp.route("/new", methods=["GET", "POST"])
@manage
def register():
    election_id = to_int(request.values.get("election"))
    election = services.get_election(election_id) if election_id else None

    # Step 1: choose the election
    if election is None:
        return render_template("candidates/form.html", mode="choose", election=None,
                               elections=services.get_registrable_elections(), form={}, errors=[], positions=[])

    # Step 2: the registration form
    errors, form = [], {"student_number": "",
                        "position_id": "", "platform": ""}
    if election["status"] not in services.REGISTRATION_STATUSES:
        flash("This election no longer accepts candidate registrations.", "error")
        return redirect(url_for("elections.detail", election_id=election["id"]))
    positions = services.get_election_positions(election["id"])

    if request.method == "POST":
        form = {key: request.form.get(key, "").strip() for key in form}
        position_id = to_int(form["position_id"])
        student, problem = services.find_student_for_election(
            election, form["student_number"])
        if problem:
            errors.append(problem)
        if not services.valid_position(election["id"], position_id):
            errors.append("Please choose one of this election's positions.")
        errors += services.validate_platform(form["platform"])

        if not errors:
            try:
                candidate_id = services.register_candidate(
                    election, student, position_id, form["platform"], g.user["id"])
            except mysql.connector.IntegrityError:
                errors.append(
                    "That student is already registered as a candidate in this election.")
            else:
                flash(
                    f"Candidate {student['student_number']} was registered (pending review).", "success")
                return redirect(url_for("candidates.detail", candidate_id=candidate_id))

    return render_template("candidates/form.html", mode="create", election=election, positions=positions,
                           form=form, errors=errors, elections=[], candidate=None)


# --------------------------------------------------------------- profile

@candidates_bp.route("/<int:candidate_id>")
@manage
def detail(candidate_id):
    candidate = _get_or_404(candidate_id)
    return render_template("candidates/detail.html", candidate=candidate, can_edit=services.can_edit(candidate),
                           actions=services.REVIEW_ACTIONS)


# ------------------------------------------------------------------ edit

@candidates_bp.route("/<int:candidate_id>/edit", methods=["GET", "POST"])
@manage
def edit(candidate_id):
    candidate = _get_or_404(candidate_id)
    if not services.can_edit(candidate):
        flash("This candidate can no longer be edited.", "error")
        return redirect(url_for("candidates.detail", candidate_id=candidate_id))

    positions = services.get_election_positions(candidate["election_id"])
    form = {"position_id": str(
        candidate["position_id"]), "platform": candidate["platform"] or ""}
    errors = []
    if request.method == "POST":
        form = {key: request.form.get(key, "").strip() for key in form}
        position_id = to_int(form["position_id"])
        if not services.valid_position(candidate["election_id"], position_id):
            errors.append("Please choose one of this election's positions.")
        errors += services.validate_platform(form["platform"])
        if not errors:
            was_reset = services.update_candidate(
                candidate, position_id, form["platform"], g.user["id"])
            flash("The candidate was updated." + (" The approval was removed, so the candidate needs a new review."
                                                  if was_reset else ""), "success")
            return redirect(url_for("candidates.detail", candidate_id=candidate_id))

    election = {"id": candidate["election_id"],
                "name": candidate["election_name"]}
    return render_template("candidates/form.html", mode="edit", election=election, positions=positions,
                           form=form, errors=errors, elections=[], candidate=candidate)


# ---------------------------------------------------------------- review

@candidates_bp.route("/<int:candidate_id>/review/<action>", methods=["POST"])
@manage
def review(candidate_id, action):
    if action not in services.REVIEW_ACTIONS:
        abort(404)
    candidate = _get_or_404(candidate_id)
    remarks = request.form.get("remarks", "").strip()
    error = services.review(candidate, action, remarks, g.user["id"])
    if error:
        flash(error, "error")
    else:
        flash(
            f"Candidate {candidate['student_number']} was {services.PAST[action]}.", "success")

    target = request.form.get("next", "")
    if is_safe_next(target):
        return redirect(target)
    return redirect(url_for("candidates.detail", candidate_id=candidate_id))
