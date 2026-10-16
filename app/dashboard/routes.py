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


@dashboard_bp.route("/school-admin/dashboard")
@role_required("school_admin")
def school_admin_home():
    return render_template("school_admin/dashboard.html",
                           pending_events=proposals.pending_count(
                               proposals.EVENT),
                           pending_projects=proposals.pending_count(
                               proposals.PROJECT),
                           pending_budgets=finance.pending_count(
                               finance.BUDGET),
                           pending_expenses=finance.pending_count(finance.EXPENSE))


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


@dashboard_bp.route("/profile")
@login_required
def profile():
    return render_template("profile.html")
