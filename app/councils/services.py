from datetime import date

from app.audit.services import log_action
from app.db import fetch_all, fetch_one, get_db
from app.utils import escape_like, get_page, to_int

PER_PAGE = 10
STATUSES = ("active", "completed", "archived")
# A council can be linked to an election only after voting has ended
LINKABLE_ELECTION_STATUSES = (
    "closed", "pending_verification", "verified", "published")

# action -> (statuses it may start from, status it leads to)
ACTIONS = {
    "complete": (("active",), "completed"),
    "archive":  (("completed",), "archived"),
    "restore":  (("archived",), "completed"),
}
AUDIT_ACTIONS = {"complete": "council_completed",
                 "archive": "council_archived", "restore": "council_restored"}


# ================================================================ lookups

def get_form_options(council=None):
    departments = fetch_all(
        "SELECT id, name FROM departments WHERE is_active = 1 ORDER BY id")
    years = fetch_all(
        "SELECT id, name FROM school_years WHERE status IN ('active', 'upcoming') ORDER BY start_date DESC")
    if council is not None:
        if not any(d["id"] == council["department_id"] for d in departments):
            departments.append(
                {"id": council["department_id"], "name": council["department"] + " (inactive)"})
        if not any(y["id"] == council["school_year_id"] for y in years):
            years.append(
                {"id": council["school_year_id"], "name": council["school_year"]})
    placeholders = ", ".join(["%s"] * len(LINKABLE_ELECTION_STATUSES))
    elections = fetch_all(
        "SELECT e.id, e.name, d.name AS department, sy.name AS school_year FROM elections e "
        "JOIN departments d ON d.id = e.department_id JOIN school_years sy ON sy.id = e.school_year_id "
        f"WHERE e.status IN ({placeholders}) ORDER BY e.start_at DESC", LINKABLE_ELECTION_STATUSES)
    return departments, years, elections


def get_filter_options():
    return {
        "departments": fetch_all("SELECT id, name FROM departments ORDER BY id"),
        "school_years": fetch_all("SELECT id, name FROM school_years ORDER BY start_date DESC"),
    }


# ==================================================================== list

def list_councils(args):
    q = args.get("q", "").strip()[:100]
    department = to_int(args.get("department"))
    school_year = to_int(args.get("school_year"))
    status = args.get("status", "")
    if status not in STATUSES:
        status = ""

    where, params = [], []
    if q:
        where.append("c.name LIKE %s")
        params.append("%" + escape_like(q) + "%")
    if department:
        where.append("c.department_id = %s")
        params.append(department)
    if school_year:
        where.append("c.school_year_id = %s")
        params.append(school_year)
    if status:
        where.append("c.status = %s")
        params.append(status)
    else:
        where.append("c.status <> 'archived'")
    where_sql = "WHERE " + " AND ".join(where)

    total = fetch_one("SELECT COUNT(*) AS n FROM councils c " +
                      where_sql, tuple(params))["n"]
    page, pages = get_page(args, total, PER_PAGE)
    councils = fetch_all(
        "SELECT c.id, c.name, c.term_start, c.term_end, c.status, d.name AS department, sy.name AS school_year, "
        "       e.name AS election_name, "
        "       (SELECT COUNT(*) FROM council_officers co WHERE co.council_id = c.id AND co.is_active = 1) AS officer_count, "
        "       (c.status = 'active' AND c.term_end < CURDATE()) AS overdue "
        "FROM councils c JOIN departments d ON d.id = c.department_id "
        "JOIN school_years sy ON sy.id = c.school_year_id LEFT JOIN elections e ON e.id = c.election_id "
        + where_sql + " ORDER BY c.term_start DESC, c.id DESC LIMIT %s OFFSET %s",
        tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE))
    base_filters = {k: v for k, v in (("q", q), ("department", department), ("school_year", school_year),
                                      ("status", status)) if v}
    return {"councils": councils, "q": q, "department": department, "school_year": school_year, "status": status,
            "page": page, "pages": pages, "total": total, "base_filters": base_filters}


def get_council(council_id):
    return fetch_one(
        "SELECT c.id, c.name, c.department_id, c.school_year_id, c.election_id, c.term_start, c.term_end, c.status, "
        "       d.name AS department, sy.name AS school_year, e.name AS election_name, "
        "       (SELECT COUNT(*) FROM council_officers co WHERE co.council_id = c.id) AS officer_rows, "
        "       (c.status = 'active' AND c.term_end < CURDATE()) AS overdue "
        "FROM councils c JOIN departments d ON d.id = c.department_id "
        "JOIN school_years sy ON sy.id = c.school_year_id LEFT JOIN elections e ON e.id = c.election_id "
        "WHERE c.id = %s", (council_id,))


# ============================================================ validation

def validate_council(form, council=None, locked=False):
    """Return a list of error messages. If locked, department and school year are not checked."""
    errors = []
    if not 3 <= len(form["name"]) <= 150:
        errors.append("Council name must be between 3 and 150 characters.")

    department_id = council["department_id"] if locked else to_int(
        form["department_id"])
    year_id = council["school_year_id"] if locked else to_int(
        form["school_year_id"])
    if not locked:
        if department_id is None or not fetch_one("SELECT id FROM departments WHERE id = %s AND is_active = 1", (department_id,)):
            errors.append("Please choose an active department.")
            department_id = None
        if year_id is None or not fetch_one("SELECT id FROM school_years WHERE id = %s AND status IN ('active', 'upcoming')", (year_id,)):
            errors.append("Please choose an active or upcoming school year.")
            year_id = None

    try:
        start, end = date.fromisoformat(
            form["term_start"]), date.fromisoformat(form["term_end"])
    except ValueError:
        errors.append("Please enter a valid term start and term end date.")
    else:
        if end <= start:
            errors.append("The term end must be after the term start.")

    # Only one active council per department and school year
    if department_id and year_id and fetch_one(
            "SELECT id FROM councils WHERE department_id = %s AND school_year_id = %s AND status = 'active' AND id <> %s",
            (department_id, year_id, council["id"] if council else 0)):
        errors.append(
            "This department already has an active council for that school year.")

    election_id = to_int(form["election_id"]) if form["election_id"] else None
    if form["election_id"] and election_id is None:
        errors.append("Please choose a valid election.")
    elif election_id is not None and department_id and year_id:
        placeholders = ", ".join(["%s"] * len(LINKABLE_ELECTION_STATUSES))
        election = fetch_one(
            f"SELECT id FROM elections WHERE id = %s AND department_id = %s AND school_year_id = %s "
            f"AND status IN ({placeholders})", (election_id, department_id, year_id) + LINKABLE_ELECTION_STATUSES)
        if election is None:
            errors.append(
                "The election must be finished and belong to the same department and school year.")
    return errors


# ============================================================== changes
# Each change and its audit log entry are saved in ONE transaction.

def create_council(form, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO councils (name, department_id, school_year_id, election_id, term_start, term_end, status, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'active', %s)",
            (form["name"], int(form["department_id"]), int(form["school_year_id"]),
             to_int(form["election_id"]) if form["election_id"] else None, form["term_start"], form["term_end"], actor_id))
        new_id = cursor.lastrowid
        log_action(actor_id, "council_created", "councils", f"Created council '{form['name']}'",
                   affected_record=f"council:{new_id}", commit=False)
        db.commit()
        return new_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def update_council(council, form, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE councils SET name = %s, department_id = %s, school_year_id = %s, election_id = %s, "
            "term_start = %s, term_end = %s WHERE id = %s AND status = 'active'",
            (form["name"], int(form["department_id"]), int(form["school_year_id"]),
             to_int(form["election_id"]) if form["election_id"] else None, form["term_start"], form["term_end"], council["id"]))
        log_action(actor_id, "council_updated", "councils", f"Updated council '{council['name']}'",
                   affected_record=f"council:{council['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def _revert_role_if_unneeded(cursor, user_id):
    """After an assignment ends: a STUDENT who is no longer an officer anywhere gets the Student role back.

    Users without a student record (for example a staff officer) keep their role.
    Returns True when the role was changed.
    """
    cursor.execute("SELECT 1 FROM council_officers co JOIN councils c ON c.id = co.council_id "
                   "WHERE co.user_id = %s AND co.is_active = 1 AND c.status = 'active' LIMIT 1", (user_id,))
    if cursor.fetchone():
        return False
    cursor.execute(
        "UPDATE users u SET u.role_id = (SELECT id FROM roles WHERE name = 'student') "
        "WHERE u.id = %s AND EXISTS (SELECT 1 FROM students s WHERE s.user_id = u.id) "
        "AND u.role_id = (SELECT id FROM roles WHERE name = 'council_officer')", (user_id,))
    return cursor.rowcount == 1


def change_status(council, action, actor_id):
    """Complete, archive or restore a council. Returns an error message or None."""
    allowed_from, new_status = ACTIONS[action]
    if council["status"] not in allowed_from:
        return f"A {council['status']} council cannot be changed this way."

    db = get_db()
    cursor = db.cursor()
    try:
        # "AND status = old" protects against two admins clicking at the same time
        cursor.execute("UPDATE councils SET status = %s WHERE id = %s AND status = %s",
                       (new_status, council["id"], council["status"]))
        if cursor.rowcount != 1:
            db.rollback()
            return "The council was changed by someone else. Please refresh the page."

        detail = ""
        if action == "complete":
            cursor.execute(
                "SELECT user_id FROM council_officers WHERE council_id = %s AND is_active = 1", (council["id"],))
            users = [row[0] for row in cursor.fetchall()]
            cursor.execute("UPDATE council_officers SET is_active = 0, ended_at = NOW() "
                           "WHERE council_id = %s AND is_active = 1", (council["id"],))
            reverted = sum(
                1 for user_id in users if _revert_role_if_unneeded(cursor, user_id))
            detail = f" {len(users)} officer assignment(s) ended, {reverted} student(s) back to the Student role."
        elif action == "archive":
            cursor.execute("INSERT INTO archives (entity_type, entity_id, reason, archived_by) "
                           "VALUES ('council', %s, %s, %s)", (council["id"], f"Council '{council['name']}' archived", actor_id))
        elif action == "restore":
            cursor.execute("UPDATE archives SET restored_by = %s, restored_at = NOW() "
                           "WHERE entity_type = 'council' AND entity_id = %s AND restored_at IS NULL",
                           (actor_id, council["id"]))

        log_action(actor_id, AUDIT_ACTIONS[action], "councils",
                   f"Council '{council['name']}': {council['status']} -> {new_status}.{detail}",
                   affected_record=f"council:{council['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


# ================================================================ officers

def get_officers(council_id):
    """Returns (active officers, past officers) of one council."""
    rows = fetch_all(
        "SELECT co.id, co.is_active, co.created_at, co.ended_at, co.position_id, u.full_name, u.username, "
        "       s.student_number, s.year_level, s.section, p.name AS position_name "
        "FROM council_officers co JOIN users u ON u.id = co.user_id "
        "LEFT JOIN students s ON s.id = co.student_id JOIN positions p ON p.id = co.position_id "
        "WHERE co.council_id = %s ORDER BY p.display_order, p.id, u.full_name", (council_id,))
    return [r for r in rows if r["is_active"]], [r for r in rows if not r["is_active"]]


def get_officer(officer_id):
    return fetch_one(
        "SELECT co.id, co.council_id, co.user_id, co.position_id, co.is_active, u.full_name, u.username, "
        "       p.name AS position_name FROM council_officers co JOIN users u ON u.id = co.user_id "
        "JOIN positions p ON p.id = co.position_id WHERE co.id = %s", (officer_id,))


def get_positions_for_assignment(council_id):
    """Active positions with how many seats are already filled in this council."""
    return fetch_all(
        "SELECT p.id, p.name, p.seats, "
        "  (SELECT COUNT(*) FROM council_officers co WHERE co.council_id = %s AND co.position_id = p.id AND co.is_active = 1) AS filled "
        "FROM positions p WHERE p.is_active = 1 ORDER BY p.display_order, p.id", (council_id,))


def find_student_for_council(council, student_number):
    """Return (student, None) if the student can be made an officer, else (None, reason)."""
    student = fetch_one(
        "SELECT s.id, s.user_id, s.student_number, s.first_name, s.last_name, s.department_id, s.school_year_id, "
        "       s.status, u.is_active AS login_enabled, r.name AS role "
        "FROM students s JOIN users u ON u.id = s.user_id JOIN roles r ON r.id = u.role_id "
        "WHERE s.student_number = %s", (student_number,))
    if student is None:
        return None, "No student has that Student ID."
    if student["status"] != "active" or not student["login_enabled"]:
        return None, "That student is not active."
    if student["department_id"] != council["department_id"]:
        return None, f"That student is not in the {council['department']} department of this council."
    if student["school_year_id"] != council["school_year_id"]:
        return None, f"That student is not enrolled in school year {council['school_year']}."
    if student["role"] not in ("student", "council_officer"):
        return None, "That account has a different role and cannot be made an officer."
    if fetch_one("SELECT id FROM council_officers WHERE council_id = %s AND user_id = %s AND is_active = 1",
                 (council["id"], student["user_id"])):
        return None, "That student is already an officer of this council."
    return student, None


def _position_problem(council, student_id, position_id, ignore_officer_id=0):
    """Check seats and the 'elected seat' rule. Returns an error message or None."""
    position = fetch_one("SELECT name, seats, is_active FROM positions WHERE id = %s",
                         (position_id,)) if position_id else None
    if position is None or not position["is_active"]:
        return "Please choose an active position."
    filled = fetch_one("SELECT COUNT(*) AS n FROM council_officers WHERE council_id = %s AND position_id = %s "
                       "AND is_active = 1 AND id <> %s", (council["id"], position_id, ignore_officer_id))["n"]
    if filled >= position["seats"]:
        return f"All {position['seats']} seat(s) of {position['name']} are already filled."

    # If the council comes from an election and this position was on its ballot, the seat is an ELECTED seat
    if council["election_id"] and fetch_one("SELECT 1 FROM election_positions WHERE election_id = %s AND position_id = %s",
                                            (council["election_id"], position_id)):
        if not fetch_one("SELECT 1 FROM candidates WHERE election_id = %s AND student_id = %s AND position_id = %s "
                         "AND status = 'approved'", (council["election_id"], student_id, position_id)):
            return (f"{position['name']} was on the ballot of the linked election, so the officer must be an "
                    f"approved candidate for it.")
    return None


def assign_officer(council, student, position_id, actor_id):
    """Make a student an officer of the council AND give them the Council Officer role, in one transaction."""
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "SELECT status FROM councils WHERE id = %s FOR UPDATE", (council["id"],))
        row = cursor.fetchone()
        if row is None or row[0] != "active":
            db.rollback()
            return "Officers can only be assigned to an active council."

        problem = _position_problem(council, student["id"], position_id)
        if problem:
            db.rollback()
            return problem

        old = fetch_one("SELECT id FROM council_officers WHERE council_id = %s AND user_id = %s",
                        (council["id"], student["user_id"]))
        if old:      # the student served before in this council: re-appoint instead of adding a second row
            cursor.execute("UPDATE council_officers SET position_id = %s, student_id = %s, is_active = 1, ended_at = NULL "
                           "WHERE id = %s", (position_id, student["id"], old["id"]))
            officer_id = old["id"]
        else:
            cursor.execute("INSERT INTO council_officers (council_id, user_id, student_id, position_id) "
                           "VALUES (%s, %s, %s, %s)", (council["id"], student["user_id"], student["id"], position_id))
            officer_id = cursor.lastrowid

        cursor.execute("UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'council_officer') "
                       "WHERE id = %s AND role_id = (SELECT id FROM roles WHERE name = 'student')", (student["user_id"],))
        role_changed = cursor.rowcount == 1
        position_name = fetch_one(
            "SELECT name FROM positions WHERE id = %s", (position_id,))["name"]
        log_action(actor_id, "officer_assigned", "councils",
                   f"Assigned {student['student_number']} as {position_name} of '{council['name']}'"
                   + (" (role changed to Council Officer)" if role_changed else ""),
                   affected_record=f"officer:{officer_id}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def change_position(council, officer, position_id, actor_id):
    """Move an active officer to another position of the same council. Returns an error message or None."""
    if council["status"] != "active" or not officer["is_active"]:
        return "Only active officers of an active council can be changed."
    student_id = fetch_one(
        "SELECT student_id FROM council_officers WHERE id = %s", (officer["id"],))["student_id"]
    problem = _position_problem(
        council, student_id, position_id, ignore_officer_id=officer["id"])
    if problem:
        return problem

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE council_officers SET position_id = %s WHERE id = %s AND is_active = 1",
                       (position_id, officer["id"]))
        new_name = fetch_one(
            "SELECT name FROM positions WHERE id = %s", (position_id,))["name"]
        log_action(actor_id, "officer_position_changed", "councils",
                   f"{officer['username']}: {officer['position_name']} -> {new_name} in '{council['name']}'",
                   affected_record=f"officer:{officer['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def remove_officer(council, officer, reason, actor_id):
    """End one officer's assignment. A student with no other assignment gets the Student role back."""
    if council["status"] != "active" or not officer["is_active"]:
        return "Only active officers of an active council can be removed."
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE council_officers SET is_active = 0, ended_at = NOW() WHERE id = %s AND is_active = 1",
                       (officer["id"],))
        if cursor.rowcount != 1:
            db.rollback()
            return "The officer was already removed."
        reverted = _revert_role_if_unneeded(cursor, officer["user_id"])
        text = f"Removed {officer['username']} ({officer['position_name']}) from '{council['name']}'"
        if reverted:
            text += " (role changed back to Student)"
        if reason:
            text += f". Reason: {reason}"
        log_action(actor_id, "officer_removed", "councils", text[:500],
                   affected_record=f"officer:{officer['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
