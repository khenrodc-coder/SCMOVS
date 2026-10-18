import mysql.connector
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from app import media
from app.auth.decorators import access_required
from app.modal_utils import json_errors, json_ok, wants_json
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

def _position_choices(election_id):
    return [(str(p["id"]), p["name"], "fa-briefcase") for p in services.get_election_positions(election_id)]


@candidates_bp.route("/new", methods=["GET", "POST"])
@manage
def register():
    """Add Candidate modal. GET returns the HTML; POST (fetch) returns JSON."""
    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("candidates.list_page"))
        elections = services.get_registrable_elections()
        pos_map = {str(e["id"]): [{"id": str(p["id"]), "name": p["name"]} for p in services.get_election_positions(e["id"])]
                   for e in elections}
        return render_template("candidates/_form_modal.html", mode="create", candidate=None, elections=elections,
                               pos_map=pos_map, selected_election=str(to_int(request.args.get("election")) or ""),
                               form={"student_number": "", "position_id": "", "platform": ""})

    errors = {}
    election_id = to_int(request.form.get("election_id"))
    election = services.get_election(election_id) if election_id else None
    student_number = request.form.get("student_number", "").strip()
    position_id = to_int(request.form.get("position_id"))
    platform = request.form.get("platform", "").strip()
    student = None
    if election is None:
        errors["election_id"] = "Please choose an election."
    elif election["status"] not in services.REGISTRATION_STATUSES:
        errors["election_id"] = "This election no longer accepts candidate registrations."
    else:
        student, problem = services.find_student_for_election(election, student_number)
        if problem:
            errors["student_number"] = problem
        if not services.valid_position(election["id"], position_id):
            errors["position_id"] = "Please choose one of this election's positions."
    for text in services.validate_platform(platform):
        errors["platform"] = text
    photo = request.files.get("photo")
    photo_path = None
    if not errors and photo is not None and photo.filename:
        photo_path, photo_error = media.save_image(photo, "candidates")      # validated before anything is stored
        if photo_error:
            errors["photo"] = photo_error
    if errors:
        return json_errors(errors)

    try:
        services.register_candidate(election, student, position_id, platform, g.user["id"], photo_path)
    except mysql.connector.IntegrityError:
        media.delete_image(photo_path)
        return json_errors({"student_number": "That student is already registered as a candidate in this election."})
    except Exception:
        media.delete_image(photo_path)
        raise
    return json_ok(f"Candidate {student['student_number']} was registered (pending review).")


@candidates_bp.route("/lookup")
@manage
def lookup():
    """Used by the Add Candidate modal: names + department of the student typed in, or why they can't run."""
    election = services.get_election(to_int(request.args.get("election")) or 0)
    if election is None:
        return jsonify(ok=False, message="Choose an election first."), 404
    info, problem = services.student_summary(election, request.args.get("student_number", "").strip())
    if problem:
        return jsonify(ok=False, message=problem), 404
    return jsonify(ok=True, student={k: (v or "") for k, v in info.items()})


@candidates_bp.route("/<int:candidate_id>/photo", methods=["POST"])
@manage
def change_photo(candidate_id):
    candidate = _get_or_404(candidate_id)
    if not services.can_change_photo(candidate):
        return json_errors({"photo": "The photo can no longer be changed because the election has closed."}, status=409)
    path, error = media.save_image(request.files.get("photo"), "candidates")
    if error:
        return json_errors({"photo": error}, error)
    try:
        services.update_photo(candidate, path, g.user["id"])
    except Exception:
        media.delete_image(path)
        raise
    media.delete_image(candidate["photo_path"])
    return json_ok("Candidate photo updated.", reload=True)


# --------------------------------------------------------------- profile

@candidates_bp.route("/<int:candidate_id>")
@manage
def detail(candidate_id):
    candidate = _get_or_404(candidate_id)
    return render_template("candidates/detail.html", candidate=candidate, can_edit=services.can_edit(candidate), photo_editable=services.can_change_photo(candidate),
                           actions=services.REVIEW_ACTIONS)


# ------------------------------------------------------------------ edit

@candidates_bp.route("/<int:candidate_id>/edit", methods=["GET", "POST"])
@manage
def edit(candidate_id):
    candidate = _get_or_404(candidate_id)
    if not services.can_edit(candidate):
        if request.method == "GET" and wants_json():
            return render_template("candidates/_locked.html"), 409
        return json_errors({"_form": "This candidate can no longer be edited."}, status=409)

    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("candidates.detail", candidate_id=candidate_id))
        election = {"id": candidate["election_id"], "name": candidate["election_name"]}
        return render_template("candidates/_form_modal.html", mode="edit", candidate=candidate, elections=[election],
                               pos_map={str(candidate["election_id"]): [{"id": str(p["id"]), "name": p["name"]} for p in services.get_election_positions(candidate["election_id"])]},
                               selected_election=str(candidate["election_id"]),
                               form={"student_number": candidate["student_number"], "position_id": str(candidate["position_id"]),
                                     "platform": candidate["platform"] or ""})

    errors = {}
    position_id = to_int(request.form.get("position_id"))
    platform = request.form.get("platform", "").strip()
    if not services.valid_position(candidate["election_id"], position_id):
        errors["position_id"] = "Please choose one of this election's positions."
    for text in services.validate_platform(platform):
        errors["platform"] = text
    photo = request.files.get("photo")
    photo_path = None
    if not errors and photo is not None and photo.filename:
        photo_path, photo_error = media.save_image(photo, "candidates")
        if photo_error:
            errors["photo"] = photo_error
    if errors:
        return json_errors(errors)
    try:
        was_reset = services.update_candidate(candidate, position_id, platform, g.user["id"], photo_path)
    except Exception:
        media.delete_image(photo_path)
        raise
    if photo_path:
        media.delete_image(candidate["photo_path"])        # the old photo goes only after the new data is saved
    return json_ok("The candidate was updated." + (" The approval was removed, so the candidate needs a new review." if was_reset else ""),
                   reload=True)


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
