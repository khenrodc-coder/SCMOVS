from datetime import datetime

from flask import Blueprint, Response, abort, g, render_template, request

from app.audit.services import log_action
from app.auth.decorators import access_required
from app.proposals.services import is_admin
from app.reports import services

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")

# Server-side: logged in -> role is super admin, school admin or council officer -> holds "reports.view".
# Students have no reports.view, so they get 403. What each person SEES is limited by report_scope().
access = access_required(
    ("super_admin", "school_admin", "council_officer"), "reports.view")


@reports_bp.route("")
@access
def index():
    groups = [(group, [(key, title, description) for key, (title, g_name, description, _fn) in services.REPORTS.items()
                       if g_name == group]) for group in services.GROUPS]
    return render_template("reports/index.html", groups=groups)


@reports_bp.route("/<key>")
@access
def show_report(key):
    if key not in services.REPORTS:
        abort(404)
    report = services.run_report(key, request.args, g.user)

    if request.args.get("format") == "csv":
        # Exporting data is audited: who exported which report, with how many rows.
        log_action(g.user["id"], "report_exported", "reports",
                   f"Exported '{report['title']}' as CSV ({report['count']} rows)", affected_record=f"report:{key}")
        filename = f"scmovs-{key.replace('_', '-')}-{datetime.now():%Y%m%d}.csv"
        response = Response(services.to_csv(report), mimetype="text/csv")
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.headers["Cache-Control"] = "no-store"
        return response

    context = dict(report=report, applied=services.describe_filters(report["filters"]), generated_at=datetime.now(),
                   generated_by=g.user["full_name"])
    if request.args.get("print") == "1":
        log_action(g.user["id"], "report_printed", "reports", f"Opened print view of '{report['title']}'",
                   affected_record=f"report:{key}")
        return render_template("reports/print.html", **context)
    return render_template("reports/report.html", options=services.get_options(g.user), is_admin=is_admin(g.user),
                           args=request.args, **context)
