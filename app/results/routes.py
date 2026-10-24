from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.decorators import access_any, access_required
from app.auth.services import has_permission
from app.results import services

results_bp = Blueprint("results", __name__, url_prefix="/results")

# --- Published results: everyone who may read them (students see their own department only) -----------
view_access = access_required(
    ("student", "council_officer", "school_admin", "super_admin"), "results.view_published")

# --- Managing results: administrators who calculate, verify or publish. Each ACTION below is checked again.
manage_access = access_any(("super_admin", "school_admin"),
                           ("elections.manage", "results.verify", "elections.publish"))

# action -> (permission needed, past tense for the message)
ACTIONS = {"calculate": ("elections.manage", "calculated"), "verify": ("results.verify", "verified"),
           "return": ("results.verify", "sent back"), "publish": ("elections.publish", "published")}


@results_bp.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


# ================================================================ published results

@results_bp.route("")
@view_access
def list_page():
    return render_template("results/list.html", elections=services.published_list(g.user))


@results_bp.route("/<int:election_id>")
@view_access
def view(election_id):
    election, problem = services.get_published(election_id, g.user)
    if problem == "missing":
        abort(404)
    if problem:
        abort(403, description=problem)
    positions = services.load_results(election_id, election["ballots_counted"])
    return render_template("results/view.html", election=election, positions=positions,
                           charts=services.chart_data(positions), labels=services.OUTCOME_LABELS)


# ================================================================ administration

@results_bp.route("/admin")
@manage_access
def admin_list():
    return render_template("results/admin_list.html", statuses=services.ADMIN_STATUSES, **services.list_for_admin(request.args))


def load_for_admin(election_id):
    election = services.get_election(election_id)
    if election is None or election["status"] not in services.ADMIN_STATUSES + ("archived",):
        abort(404)
    return election


@results_bp.route("/admin/<int:election_id>")
@manage_access
def admin_detail(election_id):
    election = load_for_admin(election_id)
    run_exists = election["calculated_at"] is not None
    positions = services.load_results(
        election_id, election["ballots_counted"]) if run_exists else []
    problem = services.integrity_problem(election_id, election) if run_exists and election["status"] in (
        "pending_verification", "verified") else None
    return render_template("results/admin_detail.html", election=election, positions=positions,
                           charts=services.chart_data(positions), labels=services.OUTCOME_LABELS, steps=services.STEPS,
                           states=services.action_states(g.user, election), problem=problem,
                           has_tie=any(p["has_tie"] for p in positions))


@results_bp.route("/admin/<int:election_id>/<action>", methods=["POST"])
@manage_access
def admin_action(election_id, action):
    if action not in ACTIONS:
        abort(404)
    permission, past = ACTIONS[action]
    if not has_permission(permission):
        abort(403)
    load_for_admin(election_id)
    if action == "calculate":
        problem = services.calculate(election_id, g.user)
    elif action == "verify":
        problem = services.verify(election_id, g.user, request.form.get(
            "remarks", ""), request.form.get("acknowledge_ties") == "1")
    elif action == "return":
        problem = services.send_back(
            election_id, g.user, request.form.get("reason", ""))
    else:
        problem = services.publish(election_id, g.user)
    flash(problem or f"Results {past}.", "error" if problem else "success")
    return redirect(url_for("results.admin_detail", election_id=election_id))
