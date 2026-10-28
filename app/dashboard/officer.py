"""Everything the Council Officer dashboard shows (Phase 6F).

All figures come from the database and are limited to the officer's ACTIVE councils.
Nothing here is invented: where the schema has nothing to show (for example announcements nobody
has published yet) the dashboard shows an honest empty state.

Spec note: "assigned tasks" has no table in the database, so the dashboard shows "Needs your
attention" instead: the officer's own drafts and rejected items, and meetings that still need
their attendance recorded.
"""
from decimal import Decimal

from flask import url_for

from app.db import fetch_all, fetch_one
from app.proposals.services import user_scope
from app.announcements.services import visible_for


def _num(value):
    return Decimal(str(value or 0))


def _marks(ids):
    return ", ".join(["%s"] * len(ids))


def _empty():
    zero = Decimal(0)
    return {"finance": {"approved_budget": zero, "approved_expenses": zero, "available": zero, "used_pct": None,
                        "pending_expense_total": zero, "pending_expense_count": 0,
                        "pending_budget_total": zero, "pending_budget_count": 0},
            "balances": [], "attention": [], "meetings": [], "events": [], "projects": [],
            "notifications": [], "unread": 0, "announcements": [], "multi_council": False}


# ================================================================ finance

def finance_summary(ids):
    """Approved budget - approved expenses = available balance, for the officer's active councils."""
    marks = _marks(ids)
    council = "COALESCE(ev.council_id, pr.council_id)"
    joins = "LEFT JOIN events ev ON ev.id = t.event_id LEFT JOIN projects pr ON pr.id = t.project_id"

    def total(table, column, statuses):
        row = fetch_one(f"SELECT COALESCE(SUM(t.{column}), 0) AS total, COUNT(*) AS n FROM {table} t {joins} "
                        f"WHERE t.status IN ({', '.join(['%s'] * len(statuses))}) AND {council} IN ({marks})",
                        tuple(statuses) + tuple(ids))
        return _num(row["total"]), row["n"]

    budget, _ = total("budgets", "approved_amount", ("approved",))
    spent, _ = total("expenses", "amount", ("approved",))
    pending_expenses, pending_expense_count = total(
        "expenses", "amount", ("submitted", "under_review"))
    pending_budgets, pending_budget_count = total(
        "budgets", "requested_amount", ("submitted", "under_review"))
    return {"approved_budget": budget, "approved_expenses": spent, "available": budget - spent,
            "used_pct": round(100 * spent / budget) if budget > 0 else None,
            "pending_expense_total": pending_expenses, "pending_expense_count": pending_expense_count,
            "pending_budget_total": pending_budgets, "pending_budget_count": pending_budget_count}


def activity_balances(ids, limit=6):
    """Events and projects that hold an approved budget, biggest budgets first."""
    marks = _marks(ids)
    parts = []
    for kind, label, table, column, statuses in (("event", "Event", "events", "event_id", "('approved', 'completed')"),
                                                 ("project", "Project", "projects", "project_id",
                                                  "('approved', 'in_progress', 'completed')")):
        parts.append(
            f"SELECT '{kind}' AS kind, '{label}' AS label, a.id, a.title, "
            f"(SELECT COALESCE(SUM(b.approved_amount), 0) FROM budgets b WHERE b.{column} = a.id AND b.status = 'approved') AS approved_budget, "
            f"(SELECT COALESCE(SUM(x.amount), 0) FROM expenses x WHERE x.{column} = a.id AND x.status = 'approved') AS approved_expenses "
            f"FROM {table} a WHERE a.is_archived = 0 AND a.status IN {statuses} AND a.council_id IN ({marks})")
    rows = fetch_all(" UNION ALL ".join(parts), tuple(ids) * 2)
    result = []
    for row in rows:
        budget, spent = _num(row["approved_budget"]), _num(
            row["approved_expenses"])
        if budget <= 0:
            continue
        result.append({"label": row["label"], "title": row["title"], "approved_budget": budget,
                       "approved_expenses": spent, "available": budget - spent,
                       "used_pct": round(100 * spent / budget),
                       "url": url_for(f"{row['kind']}s.detail", item_id=row["id"])})
    result.sort(key=lambda r: r["approved_budget"], reverse=True)
    return result[:limit]


# ================================================================ work that needs the officer

def needs_attention(user, ids, limit=8):
    """The officer's own drafts and rejected items, plus meetings waiting for attendance."""
    marks = _marks(ids)
    me = user["id"]
    council = "COALESCE(ev.council_id, pr.council_id)"
    joins = "LEFT JOIN events ev ON ev.id = t.event_id LEFT JOIN projects pr ON pr.id = t.project_id"
    sql = (
        f"SELECT 'event' AS kind, t.id, t.title, t.status, t.updated_at FROM events t "
        f"WHERE t.submitted_by = %s AND t.is_archived = 0 AND t.status IN ('draft', 'rejected') AND t.council_id IN ({marks}) "
        f"UNION ALL SELECT 'project', t.id, t.title, t.status, t.updated_at FROM projects t "
        f"WHERE t.submitted_by = %s AND t.is_archived = 0 AND t.status IN ('draft', 'rejected') AND t.council_id IN ({marks}) "
        f"UNION ALL SELECT 'budget', t.id, COALESCE(ev.title, pr.title), t.status, t.updated_at FROM budgets t {joins} "
        f"WHERE t.requested_by = %s AND t.status IN ('draft', 'rejected') AND {council} IN ({marks}) "
        f"UNION ALL SELECT 'expense', t.id, t.description, t.status, t.updated_at FROM expenses t {joins} "
        f"WHERE t.submitted_by = %s AND t.status IN ('draft', 'rejected') AND {council} IN ({marks}) "
        f"ORDER BY updated_at DESC LIMIT {limit}")
    params = []
    for _ in range(4):
        params += [me] + list(ids)
    rows = fetch_all(sql, tuple(params))

    names = {"event": "Event", "project": "Project",
             "budget": "Budget request", "expense": "Expense"}
    items = []
    # Meetings that have already started but are still 'scheduled' need attendance and completion.
    meetings = fetch_all(f"SELECT m.id, m.title FROM meetings m WHERE m.status = 'scheduled' AND m.meeting_at <= NOW() "
                         f"AND m.council_id IN ({marks}) ORDER BY m.meeting_at DESC LIMIT 5", tuple(ids))
    for m in meetings:
        items.append({"kind": "Meeting", "title": m["title"], "state": "Record attendance and complete it",
                      "tone": "amber", "url": url_for("meetings.detail", meeting_id=m["id"])})
    for row in rows:
        rejected = row["status"] == "rejected"
        items.append({"kind": names[row["kind"]], "title": row["title"],
                      "state": "Rejected: needs changes" if rejected else "Draft: not submitted yet",
                      "tone": "red" if rejected else "slate",
                      "url": url_for(f"{row['kind']}s.detail", item_id=row["id"])})
    return items[:limit]


# ================================================================ schedule

def upcoming_meetings(ids, limit=5):
    rows = fetch_all(
        f"SELECT m.id, m.title, m.meeting_at, m.location, c.name AS council FROM meetings m "
        f"JOIN councils c ON c.id = m.council_id WHERE m.status = 'scheduled' AND m.meeting_at > NOW() "
        f"AND m.council_id IN ({_marks(ids)}) ORDER BY m.meeting_at LIMIT {limit}", tuple(ids))
    for row in rows:
        row["url"] = url_for("meetings.detail", meeting_id=row["id"])
    return rows


def upcoming_events(ids, limit=5):
    rows = fetch_all(
        f"SELECT e.id, e.title, e.event_start, e.location, c.name AS council FROM events e "
        f"JOIN councils c ON c.id = e.council_id WHERE e.status = 'approved' AND e.is_archived = 0 "
        f"AND e.event_start >= NOW() AND e.council_id IN ({_marks(ids)}) ORDER BY e.event_start LIMIT {limit}", tuple(ids))
    for row in rows:
        row["url"] = url_for("events.detail", item_id=row["id"])
    return rows


def active_projects(ids, limit=5):
    rows = fetch_all(
        f"SELECT p.id, p.title, p.start_date, p.end_date, p.status, c.name AS council FROM projects p "
        f"JOIN councils c ON c.id = p.council_id WHERE p.status IN ('approved', 'in_progress') AND p.is_archived = 0 "
        f"AND p.council_id IN ({_marks(ids)}) ORDER BY p.end_date, p.id LIMIT {limit}", tuple(ids))
    for row in rows:
        row["url"] = url_for("projects.detail", item_id=row["id"])
    return rows


# ================================================================ communication

def recent_notifications(user_id, limit=6):
    rows = fetch_all("SELECT id, title, message, link_url, is_read, created_at FROM notifications "
                     "WHERE user_id = %s ORDER BY created_at DESC, id DESC LIMIT " + str(limit), (user_id,))
    unread = fetch_one(
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s AND is_read = 0", (user_id,))["n"]
    return rows, unread


def visible_announcements(user_id, limit=4):
    """Published announcements this officer is allowed to read.

    Audience rules: 'council' reaches every council officer; 'all_students' and 'department' reach
    officers who have a student record (in that department for 'department').
    """
    student = fetch_one(
        "SELECT department_id FROM students WHERE user_id = %s", (user_id,))
    is_student = 1 if student else 0
    department_id = student["department_id"] if student else None
    rows = fetch_all(
        "SELECT a.id, a.title, a.content, a.publish_at, a.created_at, u.full_name AS author "
        "FROM announcements a JOIN users u ON u.id = a.author_id "
        "WHERE a.status = 'published' AND (a.publish_at IS NULL OR a.publish_at <= NOW()) "
        "AND (a.target_audience = 'council' "
        "     OR (a.target_audience = 'all_students' AND %s = 1) "
        "     OR (a.target_audience = 'department' AND a.department_id = %s)) "
        "ORDER BY COALESCE(a.publish_at, a.created_at) DESC, a.id DESC LIMIT " + str(limit), (is_student, department_id))
    return rows


# ================================================================ charts

def chart_data(event_counts, project_counts, balances):
    """Plain numbers for Chart.js (no Decimal: JSON cannot carry it)."""
    groups = (("Draft", ("draft",)), ("In review", ("submitted", "under_review")), ("Approved", ("approved",)),
              ("In progress", ("in_progress",)), ("Completed", ("completed",)), ("Rejected", ("rejected",)))

    def count(counts, keys): return sum(counts.get(k, 0) for k in keys)
    return {"status": {"labels": [g[0] for g in groups],
                       "events": [count(event_counts, g[1]) for g in groups],
                       "projects": [count(project_counts, g[1]) for g in groups]},
            "budget": {"labels": [b["title"][:28] for b in balances],
                       "approved": [float(b["approved_budget"]) for b in balances],
                       "spent": [float(b["approved_expenses"]) for b in balances]}}


# ================================================================ entry point

def overview(user):
    """All dashboard data for one officer. Safe when the officer has no active council."""
    data = _empty()
    ids = user_scope(user) or []
    data["notifications"], data["unread"] = recent_notifications(user["id"])
    data["announcements"] = visible_for(user)
    if not ids:
        return data
    data["multi_council"] = len(ids) > 1
    data["finance"] = finance_summary(ids)
    data["balances"] = activity_balances(ids)
    data["attention"] = needs_attention(user, ids)
    data["meetings"] = upcoming_meetings(ids)
    data["events"] = upcoming_events(ids)
    data["projects"] = active_projects(ids)
    return data
