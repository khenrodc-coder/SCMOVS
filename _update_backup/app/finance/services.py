"""Budget requests and expenses.

The money rules (all enforced here AND by database triggers):
- a budget request or an expense needs an APPROVED event/project;
- available balance = approved budgets - approved expenses;
- an expense can only be approved while it fits in the available balance;
- the person who submitted a request can never approve it.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

import mysql.connector

from app.audit.services import log_action
from app.auth.services import has_permission
from app.db import fetch_all, fetch_one, get_db
from app.documents import services as documents
from app.proposals.services import is_admin, user_scope
from app.settings.services import get_bool
from app.utils import escape_like, get_page, to_int

PER_PAGE = 10
MAX_AMOUNT = Decimal("10000000.00")

# Table, column and permission names are OUR constants (never browser input), so they are safe inside SQL text.
BUDGET = {
    "kind": "budget", "table": "budgets", "blueprint": "budgets", "prefix": "/budgets",
    "label": "Budget request", "plural": "Budget requests", "owner_col": "requested_by", "doc_col": "supporting_document_id",
    "amount_col": "requested_amount", "submit_perm": "budgets.request", "approve_perm": "budgets.approve",
    "fields": ("requested_amount", "breakdown", "description"),
}
EXPENSE = {
    "kind": "expense", "table": "expenses", "blueprint": "expenses", "prefix": "/expenses",
    "label": "Expense", "plural": "Expenses", "owner_col": "submitted_by", "doc_col": "receipt_document_id",
    "amount_col": "amount", "submit_perm": "expenses.submit", "approve_perm": "expenses.approve",
    "fields": ("description", "amount", "expense_date"),
}
STATUSES = ("draft", "submitted", "under_review", "approved", "rejected")
EDITABLE_STATUSES = ("draft", "rejected")
ELIGIBLE = {"event": ("approved", "completed"), "project": (
    "approved", "in_progress", "completed")}

# action -> (statuses it may start from, status it leads to, who may do it)
ACTIONS = {
    "submit":       (("draft",), "submitted", "owner"),
    "withdraw":     (("submitted",), "draft", "owner"),
    "start_review": (("submitted",), "under_review", "admin"),
    "approve":      (("submitted", "under_review"), "approved", "admin"),
    "reject":       (("submitted", "under_review"), "rejected", "admin"),
}
PAST = {"submit": "submitted", "withdraw": "withdrawn", "start_review": "moved to review",
        "approve": "approved", "reject": "rejected"}


def peso(value):
    return f"\u20b1{Decimal(value):,.2f}"


def parse_amount(text):
    """'1,500.50' -> Decimal('1500.50'). Returns None unless it is a positive amount with at most 2 decimals."""
    try:
        value = Decimal(str(text).replace(",", "").strip())
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0 or value > MAX_AMOUNT or value != value.quantize(Decimal("0.01")):
        return None
    return value


# ================================================================ activities

def eligible_activities(user):
    """Approved events/projects of the officer's councils: the only things money can be requested for."""
    scope = user_scope(user)
    if not scope:
        return []
    marks = ", ".join(["%s"] * len(scope))
    rows = []
    for kind, table in (("event", "events"), ("project", "projects")):
        statuses = ELIGIBLE[kind]
        status_marks = ", ".join(["%s"] * len(statuses))
        for row in fetch_all(
                f"SELECT t.id, t.title, t.council_id, c.name AS council_name FROM {table} t JOIN councils c ON c.id = t.council_id "
                f"WHERE t.is_archived = 0 AND t.status IN ({status_marks}) AND t.council_id IN ({marks}) ORDER BY t.title",
                tuple(statuses) + tuple(scope)):
            row.update(kind=kind, key=f"{kind}:{row['id']}")
            rows.append(row)
    return rows


def find_activity(user, key):
    return next((a for a in eligible_activities(user) if a["key"] == key), None)


def get_balance(kind, activity_id):
    """Approved budget, approved expenses and what is left, for one event/project."""
    column = "event_id" if kind == "event" else "project_id"
    budget = fetch_one(
        f"SELECT COALESCE(SUM(approved_amount), 0) AS n FROM budgets WHERE {column} = %s AND status = 'approved'", (activity_id,))["n"]
    spent = fetch_one(
        f"SELECT COALESCE(SUM(amount), 0) AS n FROM expenses WHERE {column} = %s AND status = 'approved'", (activity_id,))["n"]
    return {"budget": budget, "spent": spent, "available": budget - spent}


# ================================================================ access

def _scope_sql(user):
    scope = user_scope(user)
    if scope is None:
        return "", []
    if not scope:
        return " AND 1 = 0", []
    return f" AND COALESCE(ev.council_id, pr.council_id) IN ({', '.join(['%s'] * len(scope))})", list(scope)


def check_actor(cfg, user, item, action):
    """Return an error message if this user may not do this action on this item, else None."""
    who = ACTIONS[action][2]
    scope = user_scope(user)
    if who == "owner":
        if (user["id"] != item[cfg["owner_col"]] or scope is None or item["council_id"] not in scope
                or not has_permission(cfg["submit_perm"])):
            return f"Only the officer who wrote this {cfg['label'].lower()} can do that."
    else:
        if not (is_admin(user) and has_permission(cfg["approve_perm"])):
            return "Only an admin can review finance requests."
        if user["id"] == item[cfg["owner_col"]]:
            return "You cannot review your own request."
    return None


def can_edit(cfg, user, item):
    scope = user_scope(user)
    return (item["status"] in EDITABLE_STATUSES and scope is not None and item["council_id"] in scope
            and user["id"] == item[cfg["owner_col"]] and has_permission(cfg["submit_perm"]))


def available_actions(cfg, user, item):
    return [name for name, (from_statuses, _to, _who) in ACTIONS.items()
            if item["status"] in from_statuses and check_actor(cfg, user, item, name) is None]


# ================================================================ reading

_FROM = ("FROM {table} t LEFT JOIN events ev ON ev.id = t.event_id LEFT JOIN projects pr ON pr.id = t.project_id "
         "JOIN councils c ON c.id = COALESCE(ev.council_id, pr.council_id) JOIN users u ON u.id = t.{owner} ")


def get_filter_options(user):
    if user_scope(user) is None:
        return {"councils": fetch_all("SELECT id, name FROM councils ORDER BY name")}
    return {"councils": []}


def list_items(cfg, args, user):
    q = args.get("q", "").strip()[:100]
    council = to_int(args.get("council"))
    status = args.get("status", "")
    if status not in STATUSES:
        status = ""

    scope_sql, scope_params = _scope_sql(user)
    where, params = ["1 = 1"], []
    if q:
        like = "%" + escape_like(q) + "%"
        where.append(
            "(COALESCE(ev.title, pr.title) LIKE %s OR t.description LIKE %s)")
        params += [like, like]
    if council and user_scope(user) is None:
        where.append("COALESCE(ev.council_id, pr.council_id) = %s")
        params.append(council)
    if status:
        where.append("t.status = %s")
        params.append(status)
    where_sql = "WHERE " + " AND ".join(where) + scope_sql
    params += scope_params

    source = _FROM.format(table=cfg["table"], owner=cfg["owner_col"])
    total = fetch_one(
        f"SELECT COUNT(*) AS n {source}{where_sql}", tuple(params))["n"]
    page, pages = get_page(args, total, PER_PAGE)
    items = fetch_all(
        f"SELECT t.id, t.status, t.description, t.{cfg['amount_col']} AS amount, COALESCE(ev.title, pr.title) AS activity_title, "
        f"IF(t.event_id IS NULL, 'project', 'event') AS activity_kind, c.name AS council_name, u.full_name AS owner_name "
        f"{source}{where_sql} ORDER BY t.updated_at DESC, t.id DESC LIMIT %s OFFSET %s",
        tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE))
    base_filters = {k: v for k, v in (
        ("q", q), ("council", council), ("status", status)) if v}
    return {"items": items, "q": q, "council": council, "status": status, "page": page, "pages": pages,
            "total": total, "base_filters": base_filters}


def get_item(cfg, item_id, user):
    """One item with names, or None if it does not exist or belongs to a council the user cannot see."""
    source = _FROM.format(table=cfg["table"], owner=cfg["owner_col"])
    item = fetch_one(
        f"SELECT t.*, t.{cfg['amount_col']} AS amount, COALESCE(ev.title, pr.title) AS activity_title, "
        f"IF(t.event_id IS NULL, 'project', 'event') AS activity_kind, COALESCE(ev.id, pr.id) AS activity_id, "
        f"COALESCE(ev.status, pr.status) AS activity_status, COALESCE(ev.is_archived, pr.is_archived) AS activity_archived, "
        f"COALESCE(ev.council_id, pr.council_id) AS council_id, c.name AS council_name, u.full_name AS owner_name, "
        f"rv.full_name AS reviewed_by_name, d.original_filename AS doc_name, d.file_size AS doc_size "
        f"{source}LEFT JOIN users rv ON rv.id = t.reviewed_by LEFT JOIN documents d ON d.id = t.{cfg['doc_col']} "
        f"WHERE t.id = %s", (item_id,))
    if item is None:
        return None
    scope = user_scope(user)
    if scope is not None and item["council_id"] not in scope:
        return None
    return item


def status_counts(cfg, user):
    scope_sql, params = _scope_sql(user)
    source = _FROM.format(table=cfg["table"], owner=cfg["owner_col"])
    rows = fetch_all(
        f"SELECT t.status, COUNT(*) AS n {source}WHERE 1 = 1{scope_sql} GROUP BY t.status", tuple(params))
    return {row["status"]: row["n"] for row in rows}


def pending_count(cfg):
    return fetch_one(f"SELECT COUNT(*) AS n FROM {cfg['table']} WHERE status IN ('submitted', 'under_review')")["n"]


# ============================================================ validation

def empty_form(cfg):
    return {field: "" for field in cfg["fields"]}


def validate(cfg, form):
    errors = []
    amount_field = cfg["amount_col"]
    if parse_amount(form[amount_field]) is None:
        errors.append(
            f"Please enter a valid amount (greater than 0, at most 2 decimals, up to {peso(MAX_AMOUNT)}).")
    if cfg["kind"] == "budget":
        for field, label in (("breakdown", "Budget breakdown"), ("description", "Description")):
            if not 10 <= len(form[field]) <= 5000:
                errors.append(
                    f"{label} must be between 10 and 5000 characters.")
    else:
        if not 3 <= len(form["description"]) <= 500:
            errors.append("Description must be between 3 and 500 characters.")
        try:
            day = date.fromisoformat(form["expense_date"])
        except ValueError:
            errors.append("Please enter a valid expense date.")
        else:
            if day > fetch_one("SELECT CURDATE() AS d")["d"]:
                errors.append("The expense date cannot be in the future.")
    return errors


def form_from_item(cfg, item):
    return {field: ("" if item[field] is None else str(item[field])) for field in cfg["fields"]}


def _values(cfg, form):
    values = []
    for field in cfg["fields"]:
        values.append(parse_amount(
            form[field]) if field == cfg["amount_col"] else form[field])
    return values


# ============================================================== changes
# Each change and its audit log entry are saved in ONE transaction.

def _friendly(problem):
    """Database trigger messages (SQLSTATE 45000) are written for people; anything else is a real error."""
    if getattr(problem, "errno", None) == 1644:
        return problem.msg
    raise problem


def create_item(cfg, form, activity, info, user):
    """Returns (new_id, None) or (None, error). `info` is a file already saved by documents.prepare_upload."""
    db = get_db()
    cursor = db.cursor()
    try:
        document_id = None
        if info:
            document_id = documents.add_document_row(
                cursor, info, f"{cfg['label']} document", user["id"], activity["council_id"],
                activity["id"] if activity["kind"] == "event" else None,
                activity["id"] if activity["kind"] == "project" else None, category="financial")
        columns = ", ".join(cfg["fields"])
        marks = ", ".join(["%s"] * len(cfg["fields"]))
        cursor.execute(
            f"INSERT INTO {cfg['table']} (event_id, project_id, {columns}, {cfg['doc_col']}, status, {cfg['owner_col']}) "
            f"VALUES (%s, %s, {marks}, %s, 'draft', %s)",
            [activity["id"] if activity["kind"] == "event" else None,
             activity["id"] if activity["kind"] == "project" else None] + _values(cfg, form) + [document_id, user["id"]])
        new_id = cursor.lastrowid
        log_action(user["id"], f"{cfg['kind']}_created", cfg["table"],
                   f"Created {cfg['kind']} of {peso(parse_amount(form[cfg['amount_col']]))} for {activity['kind']} '{activity['title']}'",
                   affected_record=f"{cfg['kind']}:{new_id}", commit=False)
        db.commit()
        return new_id, None
    except mysql.connector.Error as problem:
        db.rollback()
        documents.discard(info)
        return None, _friendly(problem)
    except Exception:
        db.rollback()
        documents.discard(info)
        raise
    finally:
        cursor.close()


def update_item(cfg, item, form, info, user):
    """Save changes. A rejected request goes back to draft so it can be sent again. Returns an error or None."""
    reset = item["status"] == "rejected"
    assignments = ", ".join(f"{field} = %s" for field in cfg["fields"])
    values = _values(cfg, form)
    db = get_db()
    cursor = db.cursor()
    try:
        if info:
            document_id = documents.add_document_row(
                cursor, info, f"{cfg['label']} document", user["id"], item["council_id"],
                item["activity_id"] if item["activity_kind"] == "event" else None,
                item["activity_id"] if item["activity_kind"] == "project" else None, category="financial")
            assignments += f", {cfg['doc_col']} = %s"
            values.append(document_id)
        if reset:
            assignments += ", status = 'draft', reviewed_by = NULL, reviewed_at = NULL, review_remarks = NULL, submitted_at = NULL"
            if cfg["kind"] == "budget":
                assignments += ", approved_amount = NULL"
        cursor.execute(f"UPDATE {cfg['table']} SET {assignments} WHERE id = %s AND status IN ('draft', 'rejected')",
                       values + [item["id"]])
        log_action(user["id"], f"{cfg['kind']}_updated", cfg["table"],
                   f"Updated {cfg['kind']} #{item['id']} of '{item['activity_title']}'" + (
                       " (back to draft after rejection)" if reset else ""),
                   affected_record=f"{cfg['kind']}:{item['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        documents.discard(info)
        raise
    finally:
        cursor.close()


def _submit_problem(cfg, item):
    if item["activity_archived"] or item["activity_status"] not in ELIGIBLE[item["activity_kind"]]:
        return f"The {item['activity_kind']} is no longer approved, so money cannot be requested for it."
    if cfg["kind"] == "expense" and not item["receipt_document_id"]:
        return "Please attach the receipt before submitting the expense."
    return None


def change_status(cfg, item, action, user, remarks="", approved_amount_text=""):
    """Run one workflow action. Returns an error message, or None when it worked."""
    from_statuses, new_status, _who = ACTIONS[action]
    problem = check_actor(cfg, user, item, action)
    if problem:
        return problem
    if item["status"] not in from_statuses:
        return f"A {item['status'].replace('_', ' ')} {cfg['label'].lower()} cannot be {PAST[action]}."

    remarks = remarks.strip()
    if len(remarks) > 500:
        return "Remarks must be 500 characters or fewer."
    if action == "reject" and not remarks:
        return "Please write the reason (remarks) for rejecting this request."
    if action == "submit":
        problem = _submit_problem(cfg, item)
        if problem:
            return problem

    approved_amount = None
    if cfg["kind"] == "budget" and action == "approve":
        approved_amount = parse_amount(
            approved_amount_text) if approved_amount_text.strip() else item["requested_amount"]
        if approved_amount is None or approved_amount > item["requested_amount"]:
            return f"The approved amount must be more than 0 and at most the requested {peso(item['requested_amount'])}."

    extra, values = "", [new_status]
    if action == "submit":
        extra = ", submitted_at = NOW(), reviewed_by = NULL, reviewed_at = NULL, review_remarks = NULL"
        if cfg["kind"] == "budget":
            extra += ", approved_amount = NULL"
    elif action == "withdraw":
        extra = ", submitted_at = NULL"
    elif action == "start_review":
        extra, values = ", reviewed_by = %s", values + [user["id"]]
    else:                                                           # approve / reject
        extra, values = ", reviewed_by = %s, reviewed_at = NOW(), review_remarks = %s", values + \
            [user["id"], remarks or None]
        if approved_amount is not None:
            extra, values = extra + \
                ", approved_amount = %s", values + [approved_amount]

    db = get_db()
    cursor = db.cursor()
    try:
        if cfg["kind"] == "expense" and action == "approve":
            error = _check_balance(cursor, item)
            if error:
                db.rollback()
                return error

        # "AND status = old" protects against two people clicking at the same time
        cursor.execute(f"UPDATE {cfg['table']} SET status = %s{extra} WHERE id = %s AND status = %s",
                       values + [item["id"], item["status"]])
        if cursor.rowcount != 1:
            db.rollback()
            return "It was changed by someone else. Please refresh the page."

        if action in ("approve", "reject") and get_bool("notifications_enabled", True):
            text = f"Your {cfg['kind']} of {peso(item['amount'])} for '{item['activity_title']}' was {PAST[action]}."
            if action == "approve" and approved_amount is not None and approved_amount != item["amount"]:
                text += f" Approved amount: {peso(approved_amount)}."
            if action == "reject":
                text += f" Reason: {remarks}"
            cursor.execute("INSERT INTO notifications (user_id, title, message, related_module) VALUES (%s, %s, %s, %s)",
                           (item[cfg["owner_col"]], f"{cfg['label']} {PAST[action]}", text[:500], cfg["table"]))

        log_action(user["id"], f"{cfg['kind']}_{PAST[action].replace(' ', '_')}", cfg["table"],
                   f"{cfg['label']} #{item['id']} ({peso(item['amount'])}) for {item['activity_kind']} '{item['activity_title']}': "
                   f"{item['status']} -> {new_status}"
                   + (f". Approved amount {peso(approved_amount)}" if approved_amount is not None else "")
                   + (f". Reason: {remarks}" if action == "reject" else ""),
                   affected_record=f"{cfg['kind']}:{item['id']}", commit=False)
        db.commit()
        return None
    except mysql.connector.Error as problem:
        db.rollback()
        return _friendly(problem)
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def _check_balance(cursor, item):
    """Is there enough approved budget left for this expense? Runs inside the approval transaction.

    The event/project row is locked first, so two admins approving expenses of the same activity at the
    same moment must wait for each other. FOR UPDATE reads the newest committed data (not an old snapshot).
    """
    column = "event_id" if item["activity_kind"] == "event" else "project_id"
    table = "events" if item["activity_kind"] == "event" else "projects"
    cursor.execute(
        f"SELECT id FROM {table} WHERE id = %s FOR UPDATE", (item["activity_id"],))
    # always read a result before the next query on the same cursor
    cursor.fetchall()
    cursor.execute(f"SELECT COALESCE(SUM(approved_amount), 0) FROM budgets WHERE {column} = %s AND status = 'approved' FOR UPDATE",
                   (item["activity_id"],))
    budget = cursor.fetchone()[0]
    cursor.execute(f"SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE {column} = %s AND status = 'approved' FOR UPDATE",
                   (item["activity_id"],))
    spent = cursor.fetchone()[0]
    available = budget - spent
    if item["amount"] > available:
        return (f"Not enough approved budget: {peso(available)} is available but this expense is {peso(item['amount'])}. "
                f"Approve an additional budget request first.")
    return None
