import re
import secrets

from app.audit.services import log_action
from app.auth.services import get_setting_int
from app.db import fetch_all, fetch_one, get_db
from app.validators import (STUDENT_ID_RE, build_full_name, normalize_email, validate_email_format, validate_names,
                            validate_student_email)

PER_PAGE = 10

# Whitelist for sorting: the browser sends a KEY, we only ever use the VALUE in SQL.
SORT_COLUMNS = {
    "name": "COALESCE(NULLIF(u.last_name, ''), u.full_name)",       # the Name column is shown as LASTNAME, FIRST MIDDLE
    "username": "u.username",
    "role": "r.display_name",
    "created": "u.created_at",
}

# Students are created together with their student record (4B / Phase 5), not here.
# New accounts can be School Admin, Council Officer or Student. Super Admin is not offered: that account is not
# created from this screen (and nobody can be promoted to it here).
NEW_USER_ROLES = ("school_admin", "council_officer", "student")
STAFF_ROLES = ("school_admin", "council_officer")
STUDENT_LINKED_ROLES = ("student", "council_officer")

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,50}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# =========================================================== dashboard

def _row_value(row, key, default=None):
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, TypeError, IndexError):
        return default
    return value if value is not None else default


def _count(sql, params=()):
    row = fetch_one(sql, params)
    value = _row_value(row, "n", 0)
    return int(str(value)) if value is not None else 0


def _money(sql):
    row = fetch_one(sql)
    value = _row_value(row, "total", 0.0)
    return float(str(value)) if value is not None else 0.0


def _pretty(status):
    return status.replace("_", " ").title()


def get_dashboard_stats():
    """All numbers for the Super Admin dashboard.

    Voting numbers come ONLY from the aggregate view v_election_participation,
    so no individual ballot is ever read here.
    """
    stats: dict[str, object] = {
        "total_students": _count("SELECT COUNT(*) AS n FROM students WHERE status <> 'archived'"),
        "total_users": _count("SELECT COUNT(*) AS n FROM users"),
        "active_users": _count("SELECT COUNT(*) AS n FROM users WHERE is_active = 1"),
        "active_departments": _count("SELECT COUNT(*) AS n FROM departments WHERE is_active = 1"),
        "active_elections": _count("SELECT COUNT(*) AS n FROM elections WHERE status = 'open'"),
        "candidates": _count("SELECT COUNT(*) AS n FROM candidates"),
        "pending_candidates": _count("SELECT COUNT(*) AS n FROM candidates WHERE status = 'pending'"),
        "active_officers": _count(
            "SELECT COUNT(*) AS n FROM council_officers co JOIN councils c ON c.id = co.council_id "
            "WHERE co.is_active = 1 AND c.status = 'active'"),
        "events": _count("SELECT COUNT(*) AS n FROM events WHERE is_archived = 0"),
        "projects": _count("SELECT COUNT(*) AS n FROM projects WHERE is_archived = 0"),
    }

    year = fetch_one("SELECT name FROM school_years WHERE status = 'active'")
    stats["active_school_year"] = _row_value(year, "name", "None")
    stats["active_school_years"] = 1 if year else 0

    part = fetch_one(
        "SELECT COALESCE(SUM(p.eligible_voters), 0) AS eligible_total, "
        "       COALESCE(SUM(p.votes_cast), 0) AS cast_total "
        "FROM v_election_participation p JOIN elections e ON e.id = p.election_id "
        "WHERE e.status = 'open'")
    eligible = int(str(_row_value(part, "eligible_total", 0)))
    cast_total = int(str(_row_value(part, "cast_total", 0)))
    stats["participation_pct"] = round(
        cast_total * 100 / eligible, 1) if eligible else 0
    if stats["active_elections"] == 0:
        stats["participation_note"] = "No open election"
    else:
        stats["participation_note"] = f"{cast_total} of {eligible} eligible voters"

    approved_budgets = _money(
        "SELECT SUM(approved_amount) AS total FROM budgets WHERE status = 'approved'")
    approved_expenses = _money(
        "SELECT SUM(amount) AS total FROM expenses WHERE status = 'approved'")
    finance = {
        "approved_budgets": approved_budgets,
        "approved_expenses": approved_expenses,
        "available": approved_budgets - approved_expenses,
    }

    # ---- Department Statistics panel + the two charts (all from the database; voting only from the aggregate view) ----
    charts = {"budget_trend": _budget_trend(finance), "open_participation": _open_participation()}
    department_stats = _department_stats()

    recent_logins = fetch_all(
        "SELECT u.full_name, u.username, a.created_at, a.ip_address "
        "FROM audit_logs a JOIN users u ON u.id = a.user_id "
        "WHERE a.action = 'login' ORDER BY a.id DESC LIMIT 5")
    recent_actions = fetch_all(
        "SELECT a.action, a.module, a.description, a.created_at, u.full_name "
        "FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id "
        "WHERE a.action NOT IN ('login', 'logout', 'login_failed') "
        "ORDER BY a.id DESC LIMIT 8")

    return {
        "stats": stats,
        "finance": finance,
        "charts": charts,
        "department_stats": department_stats,
        "recent_logins": recent_logins,
        "recent_actions": recent_actions,
    }


# ====================================================== dashboard panels

# How an election's status is labelled on a Department Statistics card
_STATUS_LABELS = {"open": "OPEN", "scheduled": "SCHEDULED", "closed": "CLOSED", "pending_verification": "VERIFYING",
                  "verified": "VERIFIED", "published": "PUBLISHED"}


def _rate(part, whole):
    """Participation rate in percent, one decimal. 0.0 when nobody is eligible (never divides by zero)."""
    return round(part * 100 / whole, 1) if whole else 0.0


def _department_stats():
    """One entry per active department: the election to show (open first, then scheduled, then the most recent finished
    one) with eligible voters, votes cast and the participation rate. Drafts and archived elections are not shown."""
    rows = fetch_all(
        "SELECT d.id, d.name, e.id AS election_id, e.name AS election_name, e.status, "
        "       p.eligible_voters, p.votes_cast "
        "FROM departments d "
        "LEFT JOIN elections e ON e.id = ("
        "    SELECT e2.id FROM elections e2 WHERE e2.department_id = d.id "
        "    AND e2.status IN ('open', 'scheduled', 'closed', 'pending_verification', 'verified', 'published') "
        "    ORDER BY CASE e2.status WHEN 'open' THEN 0 WHEN 'scheduled' THEN 1 ELSE 2 END, e2.start_at DESC, e2.id DESC LIMIT 1) "
        "LEFT JOIN v_election_participation p ON p.election_id = e.id "
        "WHERE d.is_active = 1 ORDER BY d.id")
    out = []
    for r in rows:
        status = _row_value(r, "status")
        eligible = int(str(_row_value(r, "eligible_voters", 0) or 0))
        cast = int(str(_row_value(r, "votes_cast", 0) or 0))
        out.append({
            "name": str(_row_value(r, "name", "")),
            "election_name": _row_value(r, "election_name"),
            "status": status,                                           # None when the department has no election yet
            "status_label": _STATUS_LABELS.get(str(status), "NO ELECTION"),
            "eligible": eligible, "cast": cast, "rate": _rate(cast, eligible),
        })
    return out


def _open_participation():
    """Open elections only: how many have voted and how many have not yet (never a ballot's content)."""
    rows = fetch_all(
        "SELECT e.name, d.name AS department, p.eligible_voters, p.votes_cast "
        "FROM elections e JOIN departments d ON d.id = e.department_id "
        "JOIN v_election_participation p ON p.election_id = e.id "
        "WHERE e.status = 'open' ORDER BY e.end_at, e.id")
    items = []
    for r in rows:
        eligible = int(str(_row_value(r, "eligible_voters", 0) or 0))
        voted = int(str(_row_value(r, "votes_cast", 0) or 0))
        items.append({"election": str(_row_value(r, "name", "")), "department": str(_row_value(r, "department", "")),
                      "eligible": eligible, "voted": voted, "not_voted": max(eligible - voted, 0), "rate": _rate(voted, eligible)})
    return {"elections": items,
            "labels": [i["election"] for i in items],
            "voted": [i["voted"] for i in items],
            "not_voted": [i["not_voted"] for i in items],
            "eligible": [i["eligible"] for i in items],
            "rates": [i["rate"] for i in items]}


def _budget_trend(finance):
    """Approved budgets and approved expenses per month for a line chart.

    The window is the last 12 months, but starts no earlier than the first month that has data (and shows at least the
    last 6 months), so a new system is not drawn as a year of zeros. Budgets are counted in the month they were approved
    (reviewed_at); expenses in the month they were spent (expense_date).
    """
    today = fetch_one("SELECT CURDATE() AS d")["d"]
    end = (today.year, today.month)

    def months_back(n):
        y, m = end[0], end[1] - n
        while m < 1:
            y, m = y - 1, m + 12
        return (y, m)

    budgets = {str(_row_value(r, "ym")): float(_row_value(r, "total", 0) or 0) for r in fetch_all(
        "SELECT DATE_FORMAT(COALESCE(reviewed_at, submitted_at, created_at), '%Y-%m') AS ym, SUM(approved_amount) AS total "
        "FROM budgets WHERE status = 'approved' GROUP BY ym")}
    expenses = {str(_row_value(r, "ym")): float(_row_value(r, "total", 0) or 0) for r in fetch_all(
        "SELECT DATE_FORMAT(expense_date, '%Y-%m') AS ym, SUM(amount) AS total FROM expenses WHERE status = 'approved' GROUP BY ym")}

    first_data = min(list(budgets) + list(expenses), default=None)
    earliest_allowed = months_back(11)
    if first_data:
        fy, fm = int(first_data[:4]), int(first_data[5:7])
        start = min(max((fy, fm), earliest_allowed), months_back(5))
    else:
        start = months_back(5)

    labels, keys, y, m = [], [], start[0], start[1]
    while (y, m) <= end:
        keys.append(f"{y:04d}-{m:02d}")
        labels.append(f"{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][m - 1]} {y}")
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return {"labels": labels, "budgets": [round(budgets.get(k, 0.0), 2) for k in keys],
            "expenses": [round(expenses.get(k, 0.0), 2) for k in keys],
            "totals": {"budgets": finance["approved_budgets"], "expenses": finance["approved_expenses"], "available": finance["available"]}}


# ========================================================== user queries

def get_roles():
    return fetch_all("SELECT id, name, display_name FROM roles ORDER BY id")


def roles_for(role_names):
    """Roles (with display names) limited to the given names, in id order."""
    return [r for r in get_roles() if _row_value(r, "name") in role_names]


def allowed_roles_for(has_student):
    return STUDENT_LINKED_ROLES if has_student else STAFF_ROLES


def get_user(user_id):
    return fetch_one(
        "SELECT u.id, u.username, u.email, u.full_name, u.first_name, u.middle_name, u.last_name, u.photo_path, u.is_active, "
        "       u.barangay, u.purok_street, u.city_municipality, u.province, u.contact_number, "
        "       DATE_FORMAT(u.birthdate, '%Y-%m-%d') AS birthdate, "
        "       r.name AS role, r.display_name AS role_display, "
        "       (SELECT COUNT(*) FROM students s WHERE s.user_id = u.id) > 0 AS has_student, "
        "       (SELECT s.student_number FROM students s WHERE s.user_id = u.id) AS student_number, "
        "       (SELECT COUNT(*) FROM council_officers co JOIN councils c ON c.id = co.council_id "
        "         WHERE co.user_id = u.id AND co.is_active = 1 AND c.status = 'active') AS active_assignments "
        "FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = %s",
        (user_id,),
    )


def _escape_like(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_users(args):
    """Search, filter, sort, and paginate users. All values are parameterized."""
    roles = get_roles()
    valid_role_names = {
        str(_row_value(r, "name", ""))
        for r in roles
        if _row_value(r, "name") is not None and str(_row_value(r, "name", ""))
    }

    q = args.get("q", "").strip()[:100]
    role = args.get("role", "")
    status = args.get("status", "")
    sort = args.get("sort", "name")
    direction = "desc" if args.get("dir") == "desc" else "asc"
    if sort not in SORT_COLUMNS:
        sort = "name"
    if role not in valid_role_names:
        role = ""
    if status not in ("active", "inactive", "locked"):
        status = ""

    where, params = [], []
    if q:
        like = "%" + _escape_like(q) + "%"
        where.append(
            "(u.full_name LIKE %s OR u.last_name LIKE %s OR u.username LIKE %s OR u.email LIKE %s)")
        params.extend([like, like, like, like])
    if role:
        where.append("r.name = %s")
        params.append(role)
    if status == "active":
        where.append("u.is_active = 1")
    elif status == "inactive":
        where.append("u.is_active = 0")
    elif status == "locked":
        where.append("u.locked_until IS NOT NULL AND u.locked_until > NOW()")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = _count(
        "SELECT COUNT(*) AS n FROM users u JOIN roles r ON r.id = u.role_id " + where_sql, tuple(params))

    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    try:
        page = int(args.get("page", 1))
    except ValueError:
        page = 1
    page = min(max(page, 1), pages)

    # SORT_COLUMNS[sort] is from our own whitelist, never from the browser text
    users = fetch_all(
        "SELECT u.id, u.username, u.email, u.full_name, u.first_name, u.middle_name, u.last_name, u.photo_path, u.is_active, "
        "       r.display_name AS role_display, "
        "       (u.locked_until IS NOT NULL AND u.locked_until > NOW()) AS is_locked, "
        "       (s.id IS NOT NULL) AS has_student "
        "FROM users u JOIN roles r ON r.id = u.role_id "
        "LEFT JOIN students s ON s.user_id = u.id "
        + where_sql +
        f" ORDER BY {SORT_COLUMNS[sort]} {direction}, u.first_name {direction}, u.id ASC LIMIT %s OFFSET %s",
        tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE),
    )

    base_filters = {k: v for k, v in (
        ("q", q), ("role", role), ("status", status)) if v}
    return {
        "users": users, "roles": roles, "q": q, "role": role, "status": status,
        "sort": sort, "direction": direction, "page": page, "pages": pages,
        "total": total, "base_filters": base_filters,
    }


# ======================================================== validation

def validate_user_fields(form, allowed_roles, user_id=None, check_role=True, student_number=None):
    """Return {field: message}. An empty dict means the data is valid.

    form keys: username (create only), first_name, middle_name, last_name, email, role.
    student_number is passed for accounts that belong to a student record: their email must then be
    <Student ID>@holycross.edu.ph. Administrative accounts only need a valid, unique email.
    """
    errors = validate_names(form["first_name"], form["middle_name"], form["last_name"])

    if user_id is None:
        username = form["username"]
        if not USERNAME_RE.match(username):
            errors["username"] = "3-50 characters: letters, numbers, dot, underscore, or hyphen."
        elif fetch_one("SELECT id FROM users WHERE username = %s", (username,)):
            errors["username"] = "That username is already taken."

    email = form["email"]
    if student_number and STUDENT_ID_RE.fullmatch(student_number):
        problem = validate_student_email(email, student_number)
    else:
        problem = validate_email_format(email)          # staff accounts (and legacy non-8-digit student numbers)
    if problem:
        errors["email"] = problem
    elif fetch_one("SELECT id FROM users WHERE email = %s AND id <> %s", (email, user_id or 0)):
        errors["email"] = "That email address is already in use."

    if check_role and form["role"] not in allowed_roles:
        errors["role"] = "Please choose a valid role."

    return errors


# ====================================================== user changes
# Each change and its audit log entry are saved in ONE transaction.

def create_user(form, password_hash, actor_id):
    role = fetch_one(
        "SELECT id, display_name FROM roles WHERE name = %s", (form["role"],))
    role_id = _row_value(role, "id")
    if role_id is None:
        raise ValueError("Invalid user role")
    try:
        role_id = int(str(role_id))
    except (TypeError, ValueError):
        raise ValueError("Invalid user role") from None
    role_display_name = str(_row_value(role, "display_name", form["role"]))
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, email, password_hash, full_name, first_name, middle_name, last_name, "
            "barangay, purok_street, city_municipality, birthdate, contact_number, "
            "role_id, must_change_password) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
            (form["username"], form["email"], password_hash, form["full_name"],
             form["first_name"], form["middle_name"] or None, form["last_name"],
             form["barangay"], form["purok_street"], form["city_municipality"], form["birthdate"], form["contact_number"], role_id),
        )
        new_id = cursor.lastrowid
        log_action(actor_id, "user_created", "users",
                 f"Created {role_display_name} account '{form['username']}'",
                   affected_record=f"user:{new_id}", commit=False)
        db.commit()
        return new_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def update_user(user, form, actor_id):
    role_changed = form["role"] != user["role"]
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE users SET full_name = %s, first_name = %s, middle_name = %s, last_name = %s, email = %s, "
            "barangay = %s, purok_street = %s, city_municipality = %s, birthdate = %s, contact_number = %s, "
            "role_id = (SELECT id FROM roles WHERE name = %s) WHERE id = %s",
            (form["full_name"], form["first_name"], form["middle_name"] or None, form["last_name"],
             form["email"], form["barangay"], form["purok_street"], form["city_municipality"], form["birthdate"],
             form["contact_number"], form["role"], user["id"]),
        )
        if user["student_number"]:        # keep the student record's name in step with the account
            cursor.execute("UPDATE students SET first_name = %s, middle_name = %s, last_name = %s WHERE user_id = %s",
                           (form["first_name"], form["middle_name"] or None, form["last_name"], user["id"]))
        log_action(actor_id, "user_updated", "users", f"Updated account '{user['username']}'",
                   affected_record=f"user:{user['id']}", commit=False)
        if role_changed:
            log_action(actor_id, "user_role_changed", "users",
                       f"Changed role of '{user['username']}' from {user['role']} to {form['role']}",
                       affected_record=f"user:{user['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def set_user_active(user, active, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE users SET is_active = %s WHERE id = %s",
                       (1 if active else 0, user["id"]))
        action = "user_activated" if active else "user_deactivated"
        word = "Activated" if active else "Deactivated"
        log_action(actor_id, action, "users", f"{word} account '{user['username']}'",
                   affected_record=f"user:{user['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def generate_temp_password():
    """Random password with at least one letter and one number (no look-alike characters)."""
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    digits = "23456789"
    length = max(12, get_setting_int("password_min_length", 8))
    while True:
        password = "".join(secrets.choice(letters + digits)
                           for _ in range(length))
        if any(c in letters for c in password) and any(c in digits for c in password):
            return password


def reset_user_password(user, password_hash, actor_id):
    """Set a new hashed password, force a change at next login, and clear any lockout."""
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE users SET password_hash = %s, must_change_password = 1, "
            "failed_login_attempts = 0, locked_until = NULL WHERE id = %s",
            (password_hash, user["id"]),
        )
        # The password itself is NEVER written to the audit log
        log_action(actor_id, "password_reset", "users", f"Reset password of '{user['username']}'",
                   affected_record=f"user:{user['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
