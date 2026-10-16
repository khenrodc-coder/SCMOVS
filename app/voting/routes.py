from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.decorators import access_required
from app.settings.services import get_bool
from app.voting import services

voting_bp = Blueprint("voting", __name__, url_prefix="/vote")

# Server-side: logged in -> role is student (or a council officer, who is also a student) -> holds
# "voting.cast". Staff accounts without a student record are stopped in load() below.
access = access_required(("student", "council_officer"), "voting.cast")


@voting_bp.after_request
def no_cache(response):
    """Ballot pages must never be stored by the browser or shown again by the Back button."""
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def load(election_id):
    """The signed-in student and the election, or stop with 403/404.

    A student asking for another department's election (by typing the URL) gets 403.
    """
    student = services.get_student(g.user["id"])
    if student is None:
        abort(403, description="No student record is linked to your account.")
    election = services.get_election(election_id)
    problem = services.access_problem(election, student)
    if problem == "missing":
        abort(404)
    if problem:
        abort(403, description=problem[1])
    return student, election


@voting_bp.route("")
@access
def my_elections():
    student = services.get_student(g.user["id"])
    elections = services.list_elections(student) if student else []
    return render_template("voting/list.html", student=student, elections=elections)


@voting_bp.route("/<int:election_id>")
@access
def ballot(election_id):
    student, election = load(election_id)
    voted = services.my_ballot(election_id, student["id"])
    if voted:
        return redirect(url_for("voting.done", election_id=election_id))
    state = services.voting_state(election, False)
    if state != "open":
        flash({"upcoming": "Voting for this election has not started yet.",
               "not_started": "Voting for this election has not started yet.",
               "ended": "The voting period for this election has ended."}.get(state, "Voting is closed for this election."),
              "error")
        return redirect(url_for("voting.my_elections"))
    return render_template("voting/ballot.html", election=election, positions=services.ballot_positions(election_id),
                           selected={}, errors=[], needs_review=get_bool("voting_require_confirmation", True))


@voting_bp.route("/<int:election_id>/review", methods=["POST"])
@access
def review(election_id):
    student, election = load(election_id)
    if services.my_ballot(election_id, student["id"]):
        return redirect(url_for("voting.done", election_id=election_id))
    if services.voting_state(election, False) != "open":
        flash("Voting is not open for this election.", "error")
        return redirect(url_for("voting.my_elections"))
    positions = services.ballot_positions(election_id)
    selections, errors = services.parse_selections(request.form, positions)
    if errors:      # show the ballot again with what the student had chosen
        return render_template("voting/ballot.html", election=election, positions=positions, selected=selections,
                               errors=errors, needs_review=True), 400
    return render_template("voting/review.html", election=election, lines=services.review_lines(positions, selections))


@voting_bp.route("/<int:election_id>/cast", methods=["POST"])
@access
def cast(election_id):
    # same eligibility gate as every other step
    load(election_id)
    ok, message = services.cast_ballot(g.user, election_id, request.form)
    if not ok:
        flash(message, "error")
        # Already voted -> the confirmation page; anything else -> back to the ballot
        if "already voted" in message:
            return redirect(url_for("voting.done", election_id=election_id))
        return redirect(url_for("voting.ballot", election_id=election_id))
    # PRG: a refresh never re-submits
    return redirect(url_for("voting.done", election_id=election_id))


@voting_bp.route("/<int:election_id>/done")
@access
def done(election_id):
    student, election = load(election_id)
    voted = services.my_ballot(election_id, student["id"])
    if not voted:
        return redirect(url_for("voting.ballot", election_id=election_id))
    return render_template("voting/done.html", election=election, voted_at=voted["submitted_at"])
