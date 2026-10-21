"""Event and project proposals. Both kinds share the same workflow, so one set of functions serves both.

Workflow (see ACTIONS): the officer who wrote it submits it, an admin reviews it, and only
approved proposals become official council activities. Nobody approves their own proposal.
"""
from app.audit.services import log_action
from app.auth.services import has_permission
from app.db import fetch_all, fetch_one, get_db
from app.elections.services import DT_FORMAT, db_now, parse_dt
from app.settings.services import get_bool
from app.utils import escape_like, get_page, to_int

PER_PAGE = 10
ADMIN_ROLES = ("super_admin", "school_admin")

# Table and column names below are OUR constants (never browser input), so they are safe inside SQL text.
EVENT = {
    "kind": "event", "table": "events", "blueprint": "events", "prefix": "/events", "label": "Event", "plural": "Events",
    "submit_perm": "events.submit", "approve_perm": "events.approve",
    "columns": ("title", "description", "objectives", "location", "event_start", "event_end", "supporting_info"),
    "start_col": "event_start", "end_col": "event_end",
    "statuses": ("draft", "submitted", "under_review", "approved", "rejected", "completed"),
}
PROJECT = {
    "kind": "project", "table": "projects", "blueprint": "projects", "prefix": "/projects", "label": "Project", "plural": "Projects",
    "submit_perm": "projects.submit", "approve_perm": "projects.approve",
    "columns": ("title", "description", "objectives", "start_date", "end_date"),
    "start_col": "start_date", "end_col": "end_date",
    "statuses": ("draft", "submitted", "under_review", "approved", "rejected", "in_progress", "completed"),
}

# Common actions: name -> (statuses it may start from, status it leads to, who may do it)
#   owner          = the officer who wrote the proposal
#   council        = any active officer of the proposal's council
#   council_admin  = such an officer, or an admin
#   admin          = an admin who is not the author
COMMON_ACTIONS = {
    "submit":       (("draft",), "submitted", "owner"),
    "withdraw":     (("submitted",), "draft", "owner"),
    "start_review": (("submitted",), "under_review", "admin"),
    "approve":      (("submitted", "under_review"), "approved", "admin"),
    "reject":       (("submitted", "under_review"), "rejected", "admin"),
}
ACTIONS = {
    "event": dict(COMMON_ACTIONS, complete=(("approved",), "completed", "council_admin")),
    "project": dict(COMMON_ACTIONS, start=(("approved",), "in_progress", "council"),
                    complete=(("in_progress",), "completed", "council")),
}
ARCHIVABLE_STATUSES = ("draft", "rejected", "completed")
EDITABLE_STATUSES = ("draft", "rejected")
PAST = {"submit": "submitted", "withdraw": "withdrawn", "start_review": "moved to review", "approve": "approved",
        "reject": "rejected", "start": "started", "complete": "completed", "archive": "archived", "restore": "restored"}


# ================================================================ access

def is_admin(user):
    return user["role"] in ADMIN_ROLES


def user_scope(user):
    """None = may see every council (admins). Otherwise the ids of the officer's active councils."""
    if is_admin(user):
        return None
    rows = fetch_all("SELECT co.council_id FROM council_officers co JOIN councils c ON c.id = co.council_id "
                     "WHERE co.user_id = %s AND co.is_active = 1 AND c.status = 'active'", (user["id"],))
    return [row["council_id"] for row in rows]


def my_councils(user_id):
    return fetch_all("SELECT c.id, c.name FROM council_officers co JOIN councils c ON c.id = co.council_id "
                     "WHERE co.user_id = %s AND co.is_active = 1 AND c.status = 'active' ORDER BY c.name", (user_id,))


def _scope_sql(user, alias="t"):
    scope = user_scope(user)
    if scope is None:
        return "", []
    if not scope:
        return " AND 1 = 0", []
    return f" AND {alias}.council_id IN ({', '.join(['%s'] * len(scope))})", list(scope)


def check_actor(cfg, user, item, action):
    """Return an error message if this user may not do this action on this item, else None."""
    if item["is_archived"] and action != "restore":
        return f"This {cfg['label'].lower()} is archived."
    if action in ("archive", "restore"):
        return None if has_permission(cfg["approve_perm"]) and is_admin(user) else "Only an admin can do that."

    who = ACTIONS[cfg["kind"]][action][2]
    scope = user_scope(user)
    in_council = scope is not None and item["council_id"] in scope
    admin = is_admin(user) and has_permission(cfg["approve_perm"])

    if who == "owner":
        if user["id"] != item["submitted_by"] or not in_council or not has_permission(cfg["submit_perm"]):
            return f"Only the officer who wrote this {cfg['label'].lower()} can do that."
    elif who == "council":
        if not in_council or not has_permission(cfg["submit_perm"]):
            return "Only an active officer of this council can do that."
    elif who == "council_admin":
        if not admin and not (in_council and has_permission(cfg["submit_perm"])):
            return "Only an officer of this council or an admin can do that."
    elif who == "admin":
        if not admin:
            return "Only an admin can review proposals."
        if user["id"] == item["submitted_by"]:
            return "You cannot review your own proposal."
    return None


def can_edit(cfg, user, item):
    scope = user_scope(user)
    return (not item["is_archived"] and item["status"] in EDITABLE_STATUSES and scope is not None
            and item["council_id"] in scope and user["id"] == item["submitted_by"]
            and has_permission(cfg["submit_perm"]))


def available_actions(cfg, user, item):
    """Names of the buttons this user should see for this item right now."""
    names = [name for name, (from_statuses, _to, _who) in ACTIONS[cfg["kind"]].items()
             if item["status"] in from_statuses and check_actor(cfg, user, item, name) is None]
    if not item["is_archived"] and item["status"] in ARCHIVABLE_STATUSES and check_actor(cfg, user, item, "archive") is None:
        names.append("archive")
    if item["is_archived"] and check_actor(cfg, user, item, "restore") is None:
        names.append("restore")
    return names


# ================================================================ reading

def get_filter_options(user):
    if user_scope(user) is None:
        return {"councils": fetch_all("SELECT id, name FROM councils ORDER BY name")}
    return {"councils": []}


def list_items(cfg, args, user):
    q = args.get("q", "").strip()[:100]
    council = to_int(args.get("council"))
    status = args.get("status", "")
    if status not in cfg["statuses"]:
        status = ""
    archived = args.get("archived") == "1"

    scope_sql, scope_params = _scope_sql(user)
    where, params = ["t.is_archived = %s"], [1 if archived else 0]
    if q:
        where.append("t.title LIKE %s")
        params.append("%" + escape_like(q) + "%")
    if council and user_scope(user) is None:
        where.append("t.council_id = %s")
        params.append(council)
    if status:
        where.append("t.status = %s")
        params.append(status)
    where_sql = "WHERE " + " AND ".join(where) + scope_sql
    params += scope_params

    table = cfg["table"]
    total = fetch_one(
        f"SELECT COUNT(*) AS n FROM {table} t {where_sql}", tuple(params))["n"]
    page, pages = get_page(args, total, PER_PAGE)
    items = fetch_all(
        f"SELECT t.id, t.title, t.status, t.is_archived, t.{cfg['start_col']} AS starts, t.{cfg['end_col']} AS ends, "
        f"       c.name AS council_name, u.full_name AS submitted_by_name "
        f"FROM {table} t JOIN councils c ON c.id = t.council_id JOIN users u ON u.id = t.submitted_by "
        f"{where_sql} ORDER BY t.updated_at DESC, t.id DESC LIMIT %s OFFSET %s",
        tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE))
    base_filters = {k: v for k, v in (("q", q), ("council", council), ("status", status),
                                      ("archived", "1" if archived else "")) if v}
    return {"items": items, "q": q, "council": council, "status": status, "archived": archived,
            "page": page, "pages": pages, "total": total, "base_filters": base_filters}


def get_item(cfg, item_id, user):
    """One item with names, or None if it does not exist or the user may not see its council."""
    item = fetch_one(
        f"SELECT t.*, c.name AS council_name, u.full_name AS submitted_by_name, rv.full_name AS reviewed_by_name "
        f"FROM {cfg['table']} t JOIN councils c ON c.id = t.council_id JOIN users u ON u.id = t.submitted_by "
        f"LEFT JOIN users rv ON rv.id = t.reviewed_by WHERE t.id = %s", (item_id,))
    if item is None:
        return None
    scope = user_scope(user)
    if scope is not None and item["council_id"] not in scope:
        return None
    return item


def status_counts(cfg, user):
    scope_sql, params = _scope_sql(user)
    rows = fetch_all(f"SELECT t.status, COUNT(*) AS n FROM {cfg['table']} t WHERE t.is_archived = 0{scope_sql} "
                     f"GROUP BY t.status", tuple(params))
    return {row["status"]: row["n"] for row in rows}


def pending_count(cfg):
    return fetch_one(f"SELECT COUNT(*) AS n FROM {cfg['table']} WHERE is_archived = 0 "
                     f"AND status IN ('submitted', 'under_review')")["n"]


# ============================================================ validation

def empty_form(cfg):
    return {column: "" for column in cfg["columns"]}


def validate(cfg, form):
    """Return a list of error messages for the proposal fields."""
    errors = []
    if not 3 <= len(form["title"]) <= 200:
        errors.append("Title must be between 3 and 200 characters.")
    for field, label in (("description", "Description"), ("objectives", "Objectives")):
        if not 10 <= len(form[field]) <= 5000:
            errors.append(f"{label} must be between 10 and 5000 characters.")

    if cfg["kind"] == "event":
        if not 3 <= len(form["location"]) <= 200:
            errors.append("Location must be between 3 and 200 characters.")
        if len(form["supporting_info"]) > 5000:
            errors.append(
                "Supporting information must be 5000 characters or fewer.")
        start, end = parse_dt(form["event_start"]), parse_dt(form["event_end"])
        if start is None or end is None:
            errors.append("Please enter a valid start and end date/time.")
        elif end <= start:
            errors.append("The event must end after it starts.")
        elif start <= db_now():
            errors.append("The event must start in the future.")
    else:
        from datetime import date
        try:
            start, end = date.fromisoformat(
                form["start_date"]), date.fromisoformat(form["end_date"])
        except ValueError:
            errors.append("Please enter a valid start and end date.")
        else:
            if end < start:
                errors.append("The project cannot end before it starts.")
    return errors


def _db_values(cfg, form):
    """Form text -> the Python values stored in the database, in column order."""
    values = []
    for column in cfg["columns"]:
        if column in ("event_start", "event_end"):
            values.append(parse_dt(form[column]))
        elif column == "supporting_info":
            values.append(form[column] or None)
        else:
            values.append(form[column])
    return values


def form_from_item(cfg, item):
    form = {}
    for column in cfg["columns"]:
        value = item[column]
        if column in ("event_start", "event_end"):
            value = value.strftime(DT_FORMAT)
        form[column] = "" if value is None else str(value)
    return form


# ============================================================== changes
# Each change and its audit log entry are saved in ONE transaction.

def create_item(cfg, form, council_id, user):
    columns = ", ".join(cfg["columns"])
    marks = ", ".join(["%s"] * len(cfg["columns"]))
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(f"INSERT INTO {cfg['table']} (council_id, {columns}, status, submitted_by) "
                       f"VALUES (%s, {marks}, 'draft', %s)", [council_id] + _db_values(cfg, form) + [user["id"]])
        new_id = cursor.lastrowid
        council = fetch_one(
            "SELECT name FROM councils WHERE id = %s", (council_id,))["name"]
        log_action(user["id"], f"{cfg['kind']}_created", cfg["table"],
                   f"Created {cfg['kind']} proposal '{form['title']}' for {council}",
                   affected_record=f"{cfg['kind']}:{new_id}", commit=False)
        db.commit()
        return new_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def update_item(cfg, item, form, user):
    """Save changes. A rejected proposal goes back to draft so it can be sent again."""
    assignments = ", ".join(f"{column} = %s" for column in cfg["columns"])
    reset = item["status"] == "rejected"
    extra = ", status = 'draft', reviewed_by = NULL, reviewed_at = NULL, review_remarks = NULL, submitted_at = NULL" if reset else ""
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(f"UPDATE {cfg['table']} SET {assignments}{extra} WHERE id = %s AND status IN ('draft', 'rejected')",
                       _db_values(cfg, form) + [item["id"]])
        log_action(user["id"], f"{cfg['kind']}_updated", cfg["table"],
                   f"Updated {cfg['kind']} '{item['title']}'" +
                   (" (back to draft after rejection)" if reset else ""),
                   affected_record=f"{cfg['kind']}:{item['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


# What each status change writes besides the new status
EXTRA_SQL = {
    "submit": ", submitted_at = NOW(), reviewed_by = NULL, reviewed_at = NULL, review_remarks = NULL",
    "withdraw": ", submitted_at = NULL",
    "start_review": ", reviewed_by = %s",
    "approve": ", reviewed_by = %s, reviewed_at = NOW(), review_remarks = %s",
    "reject": ", reviewed_by = %s, reviewed_at = NOW(), review_remarks = %s",
    "start": "",
    "complete": "",
}


def change_status(cfg, item, action, user, remarks="", report=""):
    """Run one workflow action. Returns an error message, or None when it worked."""
    from_statuses, new_status, _who = ACTIONS[cfg["kind"]][action]
    problem = check_actor(cfg, user, item, action)
    if problem:
        return problem
    if item["status"] not in from_statuses:
        return f"A {item['status'].replace('_', ' ')} {cfg['label'].lower()} cannot be {PAST[action]}."

    remarks, report = remarks.strip(), report.strip()
    if action in ("approve", "reject") and len(remarks) > 500:
        return "Remarks must be 500 characters or fewer."
    if action == "reject" and not remarks:
        return "Please write the reason (remarks) for rejecting this proposal."
    if action == "submit":
        problems = validate(cfg, form_from_item(
            cfg, item)) if cfg["kind"] == "event" else _project_submit_problems(item)
        if problems:
            return "Please edit it first: " + problems[0]
    if cfg["kind"] == "event" and action == "complete" and item["event_end"] > db_now():
        return "An event can only be marked completed after it has ended."
    if cfg["kind"] == "project" and action == "complete" and not 20 <= len(report) <= 5000:
        return "Please write the completion report (20 to 5000 characters)."

    extra = EXTRA_SQL[action]
    values = [new_status]
    if action in ("start_review", "approve", "reject"):
        values.append(user["id"])
    if action in ("approve", "reject"):
        values.append(remarks or None)
    if cfg["kind"] == "project" and action == "complete":
        extra += ", completion_report = %s"
        values.append(report)

    db = get_db()
    cursor = db.cursor()
    try:
        # "AND status = old" protects against two people clicking at the same time
        cursor.execute(f"UPDATE {cfg['table']} SET status = %s{extra} WHERE id = %s AND status = %s",
                       values + [item["id"], item["status"]])
        if cursor.rowcount != 1:
            db.rollback()
            return "It was changed by someone else. Please refresh the page."

        if action in ("approve", "reject") and get_bool("notifications_enabled", True):
            text = f"Your {cfg['kind']} '{item['title']}' was {PAST[action]}." + \
                (f" Reason: {remarks}" if remarks and action ==
                 "reject" else "")
            cursor.execute("INSERT INTO notifications (user_id, title, message, related_module) VALUES (%s, %s, %s, %s)",
                           (item["submitted_by"], f"{cfg['label']} {PAST[action]}", text[:500], cfg["table"]))

        log_action(user["id"], f"{cfg['kind']}_{PAST[action].replace(' ', '_')}", cfg["table"],
                   f"{cfg['label']} '{item['title']}' ({item['council_name']}): {item['status']} -> {new_status}"
                   + (f". Reason: {remarks}" if remarks and action == "reject" else ""),
                   affected_record=f"{cfg['kind']}:{item['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def _project_submit_problems(item):
    row = fetch_one("SELECT %s >= CURDATE() AS ok", (item["end_date"],))
    return [] if row["ok"] else ["the project's end date has already passed."]


def set_archived(cfg, item, archive, user):
    """Archive or restore an item. The status stays as it was; only the archive flag changes."""
    action = "archive" if archive else "restore"
    problem = check_actor(cfg, user, item, action)
    if problem:
        return problem
    if archive and item["status"] not in ARCHIVABLE_STATUSES:
        return f"Only draft, rejected or completed {cfg['plural'].lower()} can be archived."
    if not archive and not item["is_archived"]:
        return "It is not archived."

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(f"UPDATE {cfg['table']} SET is_archived = %s, archived_at = {'NOW()' if archive else 'NULL'} "
                       f"WHERE id = %s AND is_archived = %s", (1 if archive else 0, item["id"], 0 if archive else 1))
        if cursor.rowcount != 1:
            db.rollback()
            return "It was changed by someone else. Please refresh the page."
        if archive:
            cursor.execute("INSERT INTO archives (entity_type, entity_id, reason, archived_by) VALUES (%s, %s, %s, %s)",
                           (cfg["kind"], item["id"], f"{cfg['label']} '{item['title']}' archived", user["id"]))
        else:
            cursor.execute("UPDATE archives SET restored_by = %s, restored_at = NOW() "
                           "WHERE entity_type = %s AND entity_id = %s AND restored_at IS NULL",
                           (user["id"], cfg["kind"], item["id"]))
        log_action(user["id"], f"{cfg['kind']}_{PAST[action]}", cfg["table"],
                   f"{cfg['label']} '{item['title']}' {PAST[action]}", affected_record=f"{cfg['kind']}:{item['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
