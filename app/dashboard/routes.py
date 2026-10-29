from flask import Blueprint, abort, g, redirect, render_template, url_for

from app.admin.services import get_dashboard_stats
from app.auth.decorators import login_required, role_required
from app.dashboard import officer
from app.dashboard import student as student_dashboard
from app.db import fetch_all, fetch_one
from app.finance import services as finance
from app.proposals import services as proposals

dashboard_bp = Blueprint("dashboard", __name__)

ROLE_HOME = {
    "super_admin": "dashboard.super_admin_home",
    "school_admin": "dashboard.school_admin_home",
    "council_officer": "dashboard.council_officer_home",
    "student": "dashboard.student_home",
}


@dashboard_bp.route("/dashboard")
@login_required
def home():
    """Send each user to the dashboard for their role."""
    endpoint = ROLE_HOME.get(g.user["role"])
    if endpoint is None:
        abort(403)
    return redirect(url_for(endpoint))


@dashboard_bp.route("/super-admin/dashboard")
@role_required("super_admin")
def super_admin_home():
    return render_template("super_admin/dashboard.html", **get_dashboard_stats())


def school_admin_charts():
    """Aggregate numbers only (no ballots). Each dataset appears only if the role holds the matching permission."""
    from app.auth.services import has_permission
    charts = {}
    if has_permission("students.view"):
        rows = fetch_all("SELECT d.name, COUNT(s.id) AS n FROM departments d "
                         "LEFT JOIN students s ON s.department_id = d.id AND s.status <> 'archived' "
                         "WHERE d.is_active = 1 GROUP BY d.id, d.name ORDER BY d.name")
        charts["departments"] = {"labels": [r["name"] for r in rows], "values": [int(r["n"]) for r in rows]}
    if has_permission("candidates.manage"):
        counts = {r["status"]: int(r["n"]) for r in fetch_all(
            "SELECT c.status, COUNT(*) AS n FROM candidates c JOIN elections e ON e.id = c.election_id "
            "WHERE e.status <> 'archived' GROUP BY c.status")}
        order = ("pending", "approved", "rejected", "disqualified")
        charts["candidates"] = {"labels": [o.title() for o in order], "values": [counts.get(o, 0) for o in order]}
    return charts


@dashboard_bp.route("/school-admin/dashboard")
@role_required("school_admin")
def school_admin_home():
    stats = fetch_one(
        "SELECT "
        "(SELECT COUNT(*) FROM students WHERE status <> 'archived') AS total_students, "
        "(SELECT COUNT(*) FROM elections WHERE status = 'open') AS open_elections, "
        "(SELECT COUNT(*) FROM candidates c "
        " JOIN elections e ON e.id = c.election_id "
        " WHERE e.status <> 'archived') AS registered_candidates, "
        "(SELECT COUNT(*) FROM elections WHERE status = 'scheduled') AS scheduled_elections"
    ) or {}

    return render_template(
        "school_admin/dashboard.html",
        charts=school_admin_charts(),
        total_students=int(stats.get("total_students") or 0),
        open_elections=int(stats.get("open_elections") or 0),
        registered_candidates=int(stats.get("registered_candidates") or 0),
        scheduled_elections=int(stats.get("scheduled_elections") or 0),
        pending_events=proposals.pending_count(proposals.EVENT),
        pending_projects=proposals.pending_count(proposals.PROJECT),
        pending_budgets=finance.pending_count(finance.BUDGET),
        pending_expenses=finance.pending_count(finance.EXPENSE)
    )
@dashboard_bp.route("/council-officer/dashboard")
@role_required("council_officer")
def council_officer_home():
    assignments = fetch_all(
        "SELECT c.name AS council_name, p.name AS position_name, c.term_start, c.term_end "
        "FROM council_officers co "
        "JOIN councils c ON c.id = co.council_id "
        "JOIN positions p ON p.id = co.position_id "
        "WHERE co.user_id = %s AND co.is_active = 1 AND c.status = 'active'",
        (g.user["id"],),
    )
    event_counts = proposals.status_counts(proposals.EVENT, g.user)
    project_counts = proposals.status_counts(proposals.PROJECT, g.user)
    # finance, schedule, attention list, notifications, announcements
    overview = officer.overview(g.user)
    return render_template("council_officer/dashboard.html", assignments=assignments,
                           event_counts=event_counts, project_counts=project_counts,
                           budget_counts=finance.status_counts(
                               finance.BUDGET, g.user),
                           expense_counts=finance.status_counts(
                               finance.EXPENSE, g.user),
                           overview=overview,
                           charts=officer.chart_data(event_counts, project_counts, overview["balances"]))


@dashboard_bp.route("/student/dashboard")
@role_required("student")
def student_home():
    student = fetch_one(
        "SELECT s.student_number, s.first_name, s.last_name, s.year_level, s.section, s.status, "
        "       d.name AS department, sy.name AS school_year "
        "FROM students s "
        "JOIN departments d ON d.id = s.department_id "
        "JOIN school_years sy ON sy.id = s.school_year_id "
        "WHERE s.user_id = %s",
        (g.user["id"],),
    )
    return render_template("student/dashboard.html", overview=student_dashboard.overview(g.user))


@dashboard_bp.route("/account")
@login_required
def profile():
    """Kept so existing links (url_for('dashboard.profile')) still work: the page now lives in app/profile."""
    return redirect(url_for("profile.page"))

