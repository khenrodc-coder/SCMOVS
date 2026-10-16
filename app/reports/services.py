"""Council reports (Phase 6E).

Who sees what:
  * Super Admin and School Admin: every council.
  * Council Officer: the councils where they are an ACTIVE officer (past councils included, so
    council history can be reported). Nobody else has the reports.view permission.
Rules:
  * Reports describe official records, so DRAFT items are never included.
  * Nothing here can reveal ballots: voting data is not part of council reports.
  * Every value from the browser is a query parameter; column and table names come from this file only.
  * A report is limited to MAX_ROWS rows; people are asked to narrow the filters when it is cut.
"""
import csv
import io
from datetime import datetime
from decimal import Decimal

from flask import current_app

from app.db import fetch_all, fetch_one
from app.proposals.services import is_admin
from app.utils import to_int

MAX_ROWS = 2000
ACTIVITY_STATUSES = ("submitted", "under_review",
                     "approved", "rejected", "completed")
FINANCE_STATUSES = ("submitted", "under_review", "approved", "rejected")
# activities that may hold money
MONEY_ELIGIBLE = "('approved', 'in_progress', 'completed')"


# ================================================================ scope and filters

def report_scope(user):
    """None = every council (admins). Otherwise the ids of the councils where the user is an active officer."""
    if is_admin(user):
        return None
    rows = fetch_all(
        "SELECT DISTINCT council_id FROM council_officers WHERE user_id = %s AND is_active = 1", (user["id"],))
    return [row["council_id"] for row in rows]


def _date(text):
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def build_where(args, user, council_col, year_col=None, status_col=None, statuses=(), date_col=None):
    """Return (where_sql, params, filters). Column names are passed in by our own code, never by the browser."""
    where, params = ["1 = 1"], []
    scope = report_scope(user)
    council = to_int(args.get("council"))
    if scope is None:
        if council:
            where.append(f"{council_col} = %s")
            params.append(council)
    elif not scope:
        where.append("1 = 0")
    else:
        where.append(f"{council_col} IN ({', '.join(['%s'] * len(scope))})")
        params += list(scope)
        council = None

    year = to_int(args.get("school_year"))
    if year and year_col:
        where.append(f"{year_col} = %s")
        params.append(year)
    else:
        year = None

    status = args.get("status", "")
    if status_col and status in statuses:
        where.append(f"{status_col} = %s")
        params.append(status)
    else:
        status = ""

    date_from, date_to = _date(
        args.get("date_from")), _date(args.get("date_to"))
    if date_col and date_from:
        where.append(f"DATE({date_col}) >= %s")
        params.append(date_from)
    if date_col and date_to:
        where.append(f"DATE({date_col}) <= %s")
        params.append(date_to)

    filters = {k: v for k, v in (("council", council), ("school_year", year), ("status", status),
                                 ("date_from", date_from.isoformat()
                                  if date_from and date_col else ""),
                                 ("date_to", date_to.isoformat() if date_to and date_col else "")) if v}
    return " AND ".join(where), params, filters


def get_options(user):
    """Drop-down choices for the filter form."""
    scope = report_scope(user)
    if scope is None:
        councils = fetch_all("SELECT id, name FROM councils ORDER BY name")
    elif scope:
        councils = fetch_all(
            f"SELECT id, name FROM councils WHERE id IN ({', '.join(['%s'] * len(scope))}) ORDER BY name", tuple(scope))
    else:
        councils = []
    return {"councils": councils if scope is None else [],
            "school_years": fetch_all("SELECT id, name FROM school_years ORDER BY start_date DESC")}


# ================================================================ cell formatting

def _symbol():
    return current_app.config.get("CURRENCY_SYMBOL", "₱")


def _num(value):
    return Decimal(str(value or 0))


def show(value, kind):
    """Text for the screen/print table."""
    if value is None or value == "":
        return "-" if kind in ("percent", "money_or_dash") else ""
    if kind == "money":
        return f"{_symbol()}{_num(value):,.2f}"
    if kind == "date":
        return value.strftime("%b %d, %Y") if hasattr(value, "strftime") else str(value)
    if kind == "datetime":
        return value.strftime("%b %d, %Y %I:%M %p") if hasattr(value, "strftime") else str(value)
    if kind == "number":
        return f"{int(value):,}"
    if kind == "percent":
        return f"{float(value):.0f}%"
    if kind == "yesno":
        return "Yes" if value else "No"
    if kind == "status":
        return str(value).replace("_", " ").capitalize()
    return str(value)


def raw(value, kind):
    """Value for the CSV file. Text that could be run as a spreadsheet formula is neutralised."""
    if value is None:
        return ""
    if kind == "money":
        return f"{_num(value):.2f}"
    if kind == "datetime":
        return value.strftime("%Y-%m-%d %H:%M") if hasattr(value, "strftime") else str(value)
    if kind == "date":
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    if kind == "yesno":
        return "Yes" if value else "No"
    if kind in ("number", "percent"):
        return str(value)
    text = show(value, kind)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


# ================================================================ the reports

def _fetch(sql, params):
    rows = fetch_all(sql + f" LIMIT {MAX_ROWS + 1}", tuple(params))
    return rows[:MAX_ROWS], len(rows) > MAX_ROWS


def _counts(rows, key="status"):
    out = {}
    for row in rows:
        out[row[key]] = out.get(row[key], 0) + 1
    return out


def _status_summary(rows, labels=("completed", "in_progress", "approved", "under_review", "submitted", "rejected")):
    counts = _counts(rows)
    return [(label.replace("_", " ").capitalize(), counts[label]) for label in labels if counts.get(label)]


def report_council_terms(args, user):
    where, params, filters = build_where(args, user, "c.id", "c.school_year_id", "c.status",
                                         ("active", "completed", "archived"), "c.term_start")
    rows, cut = _fetch(
        "SELECT c.name AS council, d.name AS department, sy.name AS school_year, c.term_start, c.term_end, c.status, "
        "(SELECT COUNT(*) FROM council_officers co WHERE co.council_id = c.id AND co.is_active = 1) AS officers, "
        "(SELECT COUNT(*) FROM events e WHERE e.council_id = c.id AND e.status <> 'draft') AS events, "
        "(SELECT COUNT(*) FROM projects p WHERE p.council_id = c.id AND p.status <> 'draft') AS projects, "
        "(SELECT COUNT(*) FROM meetings m WHERE m.council_id = c.id AND m.status <> 'cancelled') AS meetings "
        "FROM councils c JOIN departments d ON d.id = c.department_id JOIN school_years sy ON sy.id = c.school_year_id "
        f"WHERE {where} ORDER BY c.term_start DESC, c.name", params)
    columns = [("council", "Council", "text"), ("department", "Department", "text"), ("school_year", "School year", "text"),
               ("term_start", "Term start", "date"), ("term_end",
                                                      "Term end", "date"), ("status", "Status", "status"),
               ("officers", "Active officers",
                "number"), ("events", "Events", "number"),
               ("projects", "Projects", "number"), ("meetings", "Meetings", "number")]
    summary = [("Councils", len(rows)), ("Active officers", sum(r["officers"] for r in rows)),
               ("Events", sum(r["events"] for r in rows)), ("Projects", sum(r["projects"] for r in rows))]
    return columns, rows, summary, cut, filters, ("active", "completed", "archived"), "Term start"


def report_council_members(args, user):
    statuses = ("active", "former")
    where, params, filters = build_where(
        args, user, "co.council_id", "c.school_year_id", None, statuses, "co.created_at")
    status = args.get("status", "")
    if status == "active":
        where += " AND co.is_active = 1"
        filters["status"] = status
    elif status == "former":
        where += " AND co.is_active = 0"
        filters["status"] = status
    rows, cut = _fetch(
        "SELECT c.name AS council, p.name AS position, u.full_name AS officer, co.created_at AS assigned, "
        "co.ended_at AS ended, CASE WHEN co.is_active = 1 THEN 'active' ELSE 'former' END AS status "
        "FROM council_officers co JOIN councils c ON c.id = co.council_id JOIN users u ON u.id = co.user_id "
        f"JOIN positions p ON p.id = co.position_id WHERE {where} "
        "ORDER BY c.name, p.display_order, p.name, u.full_name", params)
    columns = [("council", "Council", "text"), ("position", "Position", "text"), ("officer", "Officer", "text"),
               ("assigned", "Assigned", "date"), ("ended", "Ended", "date"), ("status", "Status", "status")]
    counts = _counts(rows)
    summary = [("Assignments", len(rows)), ("Active", counts.get(
        "active", 0)), ("Former", counts.get("former", 0))]
    return columns, rows, summary, cut, filters, statuses, "Assigned"


def report_events(args, user):
    where, params, filters = build_where(args, user, "e.council_id", "c.school_year_id", "e.status",
                                         ACTIVITY_STATUSES, "e.event_start")
    rows, cut = _fetch(
        "SELECT c.name AS council, e.title, e.event_start, e.event_end, e.location, e.status, e.is_archived, "
        "u.full_name AS submitted_by, rv.full_name AS reviewed_by "
        "FROM events e JOIN councils c ON c.id = e.council_id JOIN users u ON u.id = e.submitted_by "
        f"LEFT JOIN users rv ON rv.id = e.reviewed_by WHERE e.status <> 'draft' AND {where} "
        "ORDER BY e.event_start DESC, e.id DESC", params)
    columns = [("council", "Council", "text"), ("title", "Event", "text"), ("event_start", "Starts", "datetime"),
               ("event_end", "Ends", "datetime"), ("location",
                                                   "Location", "text"), ("status", "Status", "status"),
               ("is_archived", "Archived", "yesno"), ("submitted_by", "Submitted by", "text"), ("reviewed_by", "Reviewed by", "text")]
    summary = [("Events", len(rows))] + _status_summary(rows)
    return columns, rows, summary, cut, filters, ACTIVITY_STATUSES, "Event start"


def report_projects(args, user):
    statuses = ACTIVITY_STATUSES + ("in_progress",)
    where, params, filters = build_where(
        args, user, "p.council_id", "c.school_year_id", "p.status", statuses, "p.start_date")
    rows, cut = _fetch(
        "SELECT c.name AS council, p.title, p.start_date, p.end_date, p.status, "
        "CASE WHEN p.completion_report IS NULL THEN 0 ELSE 1 END AS has_report, p.is_archived, "
        "u.full_name AS submitted_by, rv.full_name AS reviewed_by "
        "FROM projects p JOIN councils c ON c.id = p.council_id JOIN users u ON u.id = p.submitted_by "
        f"LEFT JOIN users rv ON rv.id = p.reviewed_by WHERE p.status <> 'draft' AND {where} "
        "ORDER BY p.start_date DESC, p.id DESC", params)
    columns = [("council", "Council", "text"), ("title", "Project", "text"), ("start_date", "Starts", "date"),
               ("end_date", "Ends", "date"), ("status", "Status",
                                              "status"), ("has_report", "Completion report", "yesno"),
               ("is_archived", "Archived", "yesno"), ("submitted_by", "Submitted by", "text"), ("reviewed_by", "Reviewed by", "text")]
    summary = [("Projects", len(rows))] + _status_summary(rows)
    return columns, rows, summary, cut, filters, statuses, "Project start"


def report_balances(args, user):
    """One row per event/project that may hold money: approved budget - approved expenses = available."""
    statuses = ("approved", "in_progress", "completed")
    parts, all_params, filters = [], [], {}
    for kind, label, table, alias, date_col, col in (("event", "Event", "events", "a", "a.event_start", "event_id"),
                                                     ("project", "Project", "projects", "a", "a.start_date", "project_id")):
        where, params, filters = build_where(
            args, user, "a.council_id", "c.school_year_id", "a.status", statuses, date_col)
        parts.append(
            f"SELECT c.name AS council, '{label}' AS activity_type, a.title AS activity, a.status AS status, "
            f"(SELECT COALESCE(SUM(b.approved_amount), 0) FROM budgets b WHERE b.{col} = a.id AND b.status = 'approved') AS approved_budget, "
            f"(SELECT COALESCE(SUM(x.amount), 0) FROM expenses x WHERE x.{col} = a.id AND x.status = 'approved') AS approved_expenses, "
            f"(SELECT COALESCE(SUM(x.amount), 0) FROM expenses x WHERE x.{col} = a.id AND x.status IN ('submitted', 'under_review')) AS pending_expenses "
            f"FROM {table} a JOIN councils c ON c.id = a.council_id "
            f"WHERE a.status IN {MONEY_ELIGIBLE} AND {where}")
        all_params += params
    rows, cut = _fetch(" UNION ALL ".join(
        parts) + " ORDER BY council, activity_type, activity", all_params)
    for row in rows:
        row["available"] = _num(row["approved_budget"]) - \
            _num(row["approved_expenses"])
    columns = [("council", "Council", "text"), ("activity_type", "Type", "text"), ("activity", "Event / Project", "text"),
               ("status", "Status", "status"), ("approved_budget",
                                                "Approved budget", "money"),
               ("approved_expenses", "Approved expenses",
                "money"), ("available", "Available balance", "money"),
               ("pending_expenses", "Expenses awaiting review", "money")]
    summary = [("Activities", len(rows)),
               ("Approved budget", show(
                   sum((_num(r["approved_budget"]) for r in rows), Decimal(0)), "money")),
               ("Approved expenses", show(
                   sum((_num(r["approved_expenses"]) for r in rows), Decimal(0)), "money")),
               ("Available balance", show(sum((r["available"] for r in rows), Decimal(0)), "money"))]
    return columns, rows, summary, cut, filters, statuses, "Start date"


def report_budgets(args, user):
    where, params, filters = build_where(args, user, "COALESCE(ev.council_id, pr.council_id)", "c.school_year_id",
                                         "t.status", FINANCE_STATUSES, "t.created_at")
    rows, cut = _fetch(
        "SELECT c.name AS council, CASE WHEN t.event_id IS NOT NULL THEN 'Event' ELSE 'Project' END AS activity_type, "
        "COALESCE(ev.title, pr.title) AS activity, t.requested_amount, t.approved_amount, t.status, "
        "u.full_name AS requested_by, t.submitted_at, rv.full_name AS reviewed_by, t.reviewed_at "
        "FROM budgets t LEFT JOIN events ev ON ev.id = t.event_id LEFT JOIN projects pr ON pr.id = t.project_id "
        "JOIN councils c ON c.id = COALESCE(ev.council_id, pr.council_id) JOIN users u ON u.id = t.requested_by "
        f"LEFT JOIN users rv ON rv.id = t.reviewed_by WHERE t.status <> 'draft' AND {where} "
        "ORDER BY t.created_at DESC, t.id DESC", params)
    columns = [("council", "Council", "text"), ("activity_type", "Type", "text"), ("activity", "Event / Project", "text"),
               ("requested_amount", "Requested",
                "money"), ("approved_amount", "Approved", "money"),
               ("status", "Status", "status"), ("requested_by", "Requested by", "text"),
               ("submitted_at", "Submitted", "datetime"), ("reviewed_by", "Reviewed by", "text"), ("reviewed_at", "Reviewed", "datetime")]
    approved = [r for r in rows if r["status"] == "approved"]
    summary = [("Budget requests", len(rows)), ("Approved", len(approved)),
               ("Total requested", show(
                   sum((_num(r["requested_amount"]) for r in rows), Decimal(0)), "money")),
               ("Total approved", show(sum((_num(r["approved_amount"]) for r in approved), Decimal(0)), "money"))]
    return columns, rows, summary, cut, filters, FINANCE_STATUSES, "Created"


def report_expenses(args, user):
    where, params, filters = build_where(args, user, "COALESCE(ev.council_id, pr.council_id)", "c.school_year_id",
                                         "t.status", FINANCE_STATUSES, "t.expense_date")
    rows, cut = _fetch(
        "SELECT c.name AS council, CASE WHEN t.event_id IS NOT NULL THEN 'Event' ELSE 'Project' END AS activity_type, "
        "COALESCE(ev.title, pr.title) AS activity, t.description, t.amount, t.expense_date, t.status, "
        "CASE WHEN t.receipt_document_id IS NULL THEN 0 ELSE 1 END AS has_receipt, "
        "u.full_name AS submitted_by, rv.full_name AS reviewed_by "
        "FROM expenses t LEFT JOIN events ev ON ev.id = t.event_id LEFT JOIN projects pr ON pr.id = t.project_id "
        "JOIN councils c ON c.id = COALESCE(ev.council_id, pr.council_id) JOIN users u ON u.id = t.submitted_by "
        f"LEFT JOIN users rv ON rv.id = t.reviewed_by WHERE t.status <> 'draft' AND {where} "
        "ORDER BY t.expense_date DESC, t.id DESC", params)
    columns = [("council", "Council", "text"), ("activity_type", "Type", "text"), ("activity", "Event / Project", "text"),
               ("description", "Description", "text"), ("amount",
                                                        "Amount", "money"), ("expense_date", "Date", "date"),
               ("status", "Status", "status"), ("has_receipt", "Receipt",
                                                "yesno"), ("submitted_by", "Submitted by", "text"),
               ("reviewed_by", "Reviewed by", "text")]
    approved = [r for r in rows if r["status"] == "approved"]
    pending = [r for r in rows if r["status"] in ("submitted", "under_review")]
    summary = [("Expenses", len(rows)), ("Approved", len(approved)),
               ("Approved total", show(
                   sum((_num(r["amount"]) for r in approved), Decimal(0)), "money")),
               ("Awaiting review", show(sum((_num(r["amount"]) for r in pending), Decimal(0)), "money"))]
    return columns, rows, summary, cut, filters, FINANCE_STATUSES, "Expense date"


def report_meetings(args, user):
    statuses = ("scheduled", "completed", "cancelled")
    where, params, filters = build_where(
        args, user, "m.council_id", "c.school_year_id", "m.status", statuses, "m.meeting_at")
    rows, cut = _fetch(
        "SELECT c.name AS council, m.title, m.meeting_at, m.location, m.status, "
        "(SELECT COUNT(*) FROM meeting_attendance a WHERE a.meeting_id = m.id AND a.attendance = 'present') AS present, "
        "(SELECT COUNT(*) FROM meeting_attendance a WHERE a.meeting_id = m.id AND a.attendance = 'absent') AS absent, "
        "(SELECT COUNT(*) FROM meeting_attendance a WHERE a.meeting_id = m.id AND a.attendance = 'excused') AS excused, "
        "(SELECT COUNT(*) FROM meeting_minutes mm WHERE mm.meeting_id = m.id) AS has_minutes "
        f"FROM meetings m JOIN councils c ON c.id = m.council_id WHERE {where} ORDER BY m.meeting_at DESC, m.id DESC", params)
    rates = []
    for row in rows:
        recorded = row["present"] + row["absent"] + row["excused"]
        row["rate"] = round(100 * row["present"] /
                            recorded) if recorded else None
        if row["rate"] is not None:
            rates.append(row["rate"])
    columns = [("council", "Council", "text"), ("title", "Meeting", "text"), ("meeting_at", "Date and time", "datetime"),
               ("location", "Location", "text"), ("status", "Status",
                                                  "status"), ("present", "Present", "number"),
               ("absent", "Absent", "number"), ("excused", "Excused",
                                                "number"), ("rate", "Attendance rate", "percent"),
               ("has_minutes", "Minutes", "yesno")]
    counts = _counts(rows)
    summary = [("Meetings", len(rows)), ("Completed", counts.get("completed", 0)), ("Cancelled", counts.get("cancelled", 0)),
               ("Average attendance", f"{sum(rates) / len(rates):.0f}%" if rates else "-")]
    return columns, rows, summary, cut, filters, statuses, "Meeting date"


REPORTS = {
    "council_terms": ("Council terms", "Council", "Each council with its term, department, officers and activity counts.", report_council_terms),
    "council_members": ("Council members", "Council", "Officers of each council with their positions and assignment dates, including former officers.", report_council_members),
    "events": ("Events", "Activities", "Submitted events with their schedule, status and reviewer. Drafts are not included.", report_events),
    "projects": ("Projects", "Activities", "Submitted projects with their schedule, status and completion report. Drafts are not included.", report_projects),
    "balances": ("Budget balances", "Finance", "Approved budget, approved expenses and the available balance of every approved event and project.", report_balances),
    "budgets": ("Budget requests", "Finance", "Every submitted budget request with its requested and approved amounts.", report_budgets),
    "expenses": ("Expenses", "Finance", "Every submitted expense with its status and whether a receipt is attached.", report_expenses),
    "meetings": ("Meetings and attendance", "Meetings", "Meetings with attendance counts, attendance rate and whether minutes were recorded.", report_meetings),
}
GROUPS = ("Council", "Activities", "Finance", "Meetings")


def run_report(key, args, user):
    """Run one report. Returns a dict for the templates and the CSV export."""
    title, group, description, builder = REPORTS[key]
    columns, rows, summary, cut, filters, statuses, date_label = builder(
        args, user)
    table = [[{"text": show(row.get(col[0]), col[2]),
               "align": "right" if col[2] in ("money", "number", "percent") else "left"} for col in columns] for row in rows]
    csv_rows = [[raw(row.get(col[0]), col[2])
                 for col in columns] for row in rows]
    return {"key": key, "title": title, "group": group, "description": description,
            "columns": [{"label": c[1], "align": "right" if c[2] in ("money", "number", "percent") else "left"} for c in columns],
            "rows": table, "csv_header": [c[1] for c in columns], "csv_rows": csv_rows, "summary": summary,
            "truncated": cut, "count": len(rows), "filters": filters, "statuses": statuses, "date_label": date_label,
            "has_date": date_label is not None}


def describe_filters(filters):
    """Human-readable list of the applied filters, for the print header."""
    parts = []
    if filters.get("council"):
        row = fetch_one("SELECT name FROM councils WHERE id = %s",
                        (filters["council"],))
        parts.append(("Council", row["name"] if row else "?"))
    if filters.get("school_year"):
        row = fetch_one(
            "SELECT name FROM school_years WHERE id = %s", (filters["school_year"],))
        parts.append(("School year", row["name"] if row else "?"))
    if filters.get("status"):
        parts.append(
            ("Status", filters["status"].replace("_", " ").capitalize()))
    if filters.get("date_from") or filters.get("date_to"):
        parts.append(
            ("Date range", f"{filters.get('date_from', 'start')} to {filters.get('date_to', 'today')}"))
    return parts


def to_csv(report):
    """CSV text with a UTF-8 BOM so Excel shows accents and the peso sign correctly."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(report["csv_header"])
    writer.writerows(report["csv_rows"])
    return "\ufeff" + out.getvalue()
