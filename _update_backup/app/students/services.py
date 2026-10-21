import re

from app.admin.services import generate_temp_password, reset_user_password  # noqa: F401  (reused by routes)
from app.audit.services import log_action
from app.db import fetch_all, fetch_one, get_db
from app.utils import escape_like, get_page, to_int
from app.validators import (STUDENT_ID_RE, normalize_email, validate_email_format, validate_names,
                            validate_student_email, validate_student_id)

PER_PAGE = 10

STUDENT_NUMBER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,29}$")
SECTION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]{0,29}$")
NAME_EXTRA_CHARS = set(" .'-")

STATUSES = ("active", "inactive", "graduated", "archived")

# Which status changes are allowed (anything else is rejected on the server)
STATUS_TRANSITIONS = {
    "active":    ("inactive", "graduated", "archived"),
    "inactive":  ("active", "graduated", "archived"),
    "graduated": ("active", "archived"),
    "archived":  ("inactive",),
}
# Statuses that leave the student's account switched off
LOGIN_OFF_STATUSES = ("inactive", "graduated", "archived")

# Year levels for the three built-in departments (other departments accept free text)
YEAR_LEVELS = {
    "ELEM": [f"Grade {n}" for n in range(1, 7)],
    "HS": [f"Grade {n}" for n in range(7, 13)],
    "COL": ["1st Year", "2nd Year", "3rd Year", "4th Year", "5th Year"],
}

# Sort key from the browser -> SQL. {d} becomes asc/desc (whitelisted), never browser text.
SORT_COLUMNS = {
    "student_id": "s.student_number {d}",
    "name": "s.last_name {d}, s.first_name {d}",
    "department": "d.name {d}",
    "year_level": "s.year_level {d}",
    "school_year": "sy.name {d}",
    "status": "s.status {d}",
}


# ============================================================== lookups

def get_active_departments():
    return fetch_all("SELECT id, name, code FROM departments WHERE is_active = 1 ORDER BY id")


def get_assignable_school_years():
    """School years a student can be placed in: active or upcoming."""
    return fetch_all("SELECT id, name, status FROM school_years WHERE status IN ('active', 'upcoming') "
                     "ORDER BY start_date DESC")


def year_level_map(departments):
    """{department id: [year levels]} so the form can suggest levels for the chosen department."""
    return {str(d["id"]): YEAR_LEVELS.get(d["code"], []) for d in departments}


def get_filter_options():
    return {
        "departments": fetch_all("SELECT id, name FROM departments ORDER BY id"),
        "school_years": fetch_all("SELECT id, name FROM school_years ORDER BY start_date DESC"),
        "year_levels": [r["year_level"] for r in fetch_all(
            "SELECT DISTINCT year_level FROM students ORDER BY year_level")],
        "sections": [r["section"] for r in fetch_all("SELECT DISTINCT section FROM students ORDER BY section")],
    }


# ================================================================ list

def list_students(args):
    q = args.get("q", "").strip()[:100]
    department = to_int(args.get("department"))
    school_year = to_int(args.get("school_year"))
    year_level = args.get("year_level", "").strip()[:20]
    section = args.get("section", "").strip()[:30]
    status = args.get("status", "")
    if status not in STATUSES:
        status = ""
    sort = args.get("sort", "name")
    if sort not in SORT_COLUMNS:
        sort = "name"
    direction = "desc" if args.get("dir") == "desc" else "asc"

    where, params = [], []
    if q:
        like = "%" + escape_like(q) + "%"
        where.append("(s.student_number LIKE %s OR s.first_name LIKE %s OR s.last_name LIKE %s "
                     "OR CONCAT_WS(' ', s.first_name, s.last_name) LIKE %s)")
        params.extend([like, like, like, like])
    if department:
        where.append("s.department_id = %s")
        params.append(department)
    if school_year:
        where.append("s.school_year_id = %s")
        params.append(school_year)
    if year_level:
        where.append("s.year_level = %s")
        params.append(year_level)
    if section:
        where.append("s.section = %s")
        params.append(section)
    if status:
        where.append("s.status = %s")
        params.append(status)
    else:
        # archived students only show when asked for
        where.append("s.status <> 'archived'")
    where_sql = "WHERE " + " AND ".join(where)

    total = fetch_one("SELECT COUNT(*) AS n FROM students s " +
                      where_sql, tuple(params))["n"]
    page, pages = get_page(args, total, PER_PAGE)

    order_sql = SORT_COLUMNS[sort].format(d=direction)
    students = fetch_all(
        "SELECT s.id, s.student_number, s.first_name, s.middle_name, s.last_name, s.year_level, s.section, "
        "       s.status, d.name AS department, sy.name AS school_year, u.is_active AS login_enabled "
        "FROM students s "
        "JOIN departments d ON d.id = s.department_id "
        "JOIN school_years sy ON sy.id = s.school_year_id "
        "JOIN users u ON u.id = s.user_id "
        + where_sql +
        f" ORDER BY {order_sql}, s.id ASC LIMIT %s OFFSET %s",
        tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE),
    )

    base_filters = {k: v for k, v in (("q", q), ("department", department), ("school_year", school_year),
                                      ("year_level", year_level), ("section", section), ("status", status)) if v}
    return {"students": students, "q": q, "department": department, "school_year": school_year,
            "year_level": year_level, "section": section, "status": status, "sort": sort,
            "direction": direction, "page": page, "pages": pages, "total": total, "base_filters": base_filters}


def get_student(student_id):
    """One student with everything the edit page and the rules need."""
    return fetch_one(
        "SELECT s.id, s.user_id, s.student_number, s.first_name, s.middle_name, s.last_name, s.department_id, "
        "       s.year_level, s.section, s.school_year_id, s.status, "
        "       u.username, u.full_name, u.email, u.is_active AS login_enabled, r.name AS user_role, "
        # Only counts rows. It never reads what anyone voted for.
        "       (SELECT COUNT(*) FROM ballots b WHERE b.student_id = s.id) "
        "         + (SELECT COUNT(*) FROM candidates c WHERE c.student_id = s.id) AS election_records, "
        "       (SELECT COUNT(*) FROM council_officers co JOIN councils cn ON cn.id = co.council_id "
        "         WHERE co.user_id = s.user_id AND co.is_active = 1 AND cn.status = 'active') AS active_assignments "
        "FROM students s JOIN users u ON u.id = s.user_id JOIN roles r ON r.id = u.role_id "
        "WHERE s.id = %s",
        (student_id,),
    )


# ========================================================== validation

def _valid_person_name(value, required):
    if not value:
        return not required
    return (len(value) <= 60 and value[0].isalpha()
            and all(ch.isalpha() or ch in NAME_EXTRA_CHARS for ch in value))


def build_full_name(form):
    return " ".join(part for part in (form["first_name"], form["middle_name"], form["last_name"]) if part)


def validate_student(form, student=None):
    """Check every field on the server. Returns {field: message} (empty dict = valid).

    New students: Student ID must be exactly 8 digits and the email must be <Student ID>@holycross.edu.ph.
    Existing students keep their Student ID. If it is a legacy (not 8-digit) ID, any valid email is accepted.
    On success form["year_level"] is replaced by the official spelling (for example "3rd Year").
    """
    errors = {}

    if student is None:
        number = form["student_number"]
        problem = validate_student_id(number)
        if problem:
            errors["student_number"] = problem
        elif fetch_one("SELECT id FROM students WHERE student_number = %s", (number,)):
            errors["student_number"] = "That Student ID already exists."
        elif fetch_one("SELECT id FROM users WHERE username = %s", (number,)):
            errors["student_number"] = "That Student ID is already used as a username by another account."
        number_for_email = number
    else:
        number_for_email = student["student_number"]

    errors.update(validate_names(
        form["first_name"], form["middle_name"], form["last_name"]))

    email = form["email"]
    if STUDENT_ID_RE.fullmatch(number_for_email or ""):
        problem = validate_student_email(email, number_for_email)
    else:
        problem = validate_email_format(email)
    if problem:
        errors["email"] = problem
    elif fetch_one("SELECT id FROM users WHERE email = %s AND id <> %s", (email, student["user_id"] if student else 0)):
        errors["email"] = "That email address is already in use."

    # Department: must exist and be active (unchanged departments are allowed on edit)
    department = None
    department_id = to_int(form["department_id"])
    if department_id is not None:
        department = fetch_one(
            "SELECT id, code, is_active FROM departments WHERE id = %s", (department_id,))
    if department is None:
        errors["department_id"] = "Please choose a department."
    elif not department["is_active"] and not (student and student["department_id"] == department["id"]):
        errors["department_id"] = "That department is not active."

    # Year level: official list for the built-in departments, free text for new ones
    level = form["year_level"].strip()
    if department is not None:
        official = YEAR_LEVELS.get(department["code"])
        if official:
            match = next(
                (o for o in official if o.lower() == level.lower()), None)
            if match is None:
                errors["year_level"] = "Please choose a valid year level for this department."
            else:
                form["year_level"] = match
        elif not 1 <= len(level) <= 20:
            errors["year_level"] = "Year level is required (up to 20 characters)."
    elif not level:
        errors["year_level"] = "Year level is required."

    if not SECTION_RE.match(form["section"]):
        errors["section"] = "Required (up to 30 characters: letters, numbers, space, dash, dot, slash)."

    year = None
    year_id = to_int(form["school_year_id"])
    if year_id is not None:
        year = fetch_one(
            "SELECT id, status FROM school_years WHERE id = %s", (year_id,))
    if year is None:
        errors["school_year_id"] = "Please choose a school year."
    elif year["status"] not in ("active", "upcoming") and not (student and student["school_year_id"] == year["id"]):
        errors["school_year_id"] = "Students can only be placed in an active or upcoming school year."

    return errors


# ============================================================= changes
# Each change and its audit log entry are saved in ONE transaction.

def create_student(form, password_hash, actor_id):
    """Create the login account AND the student record together. Returns the new student id."""
    role = fetch_one("SELECT id FROM roles WHERE name = 'student'")
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, email, password_hash, full_name, first_name, middle_name, last_name, "
            "role_id, must_change_password) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)",
            (form["student_number"], form["email"], password_hash, build_full_name(form), form["first_name"],
             form["middle_name"] or None, form["last_name"], role["id"]))
        user_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO students (user_id, student_number, first_name, middle_name, last_name, department_id, "
            "year_level, section, school_year_id, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (user_id, form["student_number"], form["first_name"], form["middle_name"] or None, form["last_name"],
             int(form["department_id"]), form["year_level"], form["section"], int(form["school_year_id"]), actor_id))
        student_id = cursor.lastrowid
        log_action(actor_id, "student_created", "students",
                   f"Created student {form['student_number']} ({build_full_name(form)})",
                   affected_record=f"student:{student_id}", commit=False)
        db.commit()
        return student_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def update_student(student, form, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE students SET first_name = %s, middle_name = %s, last_name = %s, department_id = %s, "
            "year_level = %s, section = %s, school_year_id = %s WHERE id = %s",
            (form["first_name"], form["middle_name"] or None, form["last_name"], int(form["department_id"]),
             form["year_level"], form["section"], int(form["school_year_id"]), student["id"]))
        cursor.execute("UPDATE users SET full_name = %s, first_name = %s, middle_name = %s, last_name = %s, email = %s WHERE id = %s",
                       (build_full_name(form), form["first_name"], form["middle_name"] or None, form["last_name"],
                        form["email"], student["user_id"]))
        log_action(actor_id, "student_updated", "students", f"Updated student {student['student_number']}",
                   affected_record=f"student:{student['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def change_status(student, new_status, actor_id):
    """Change a student's status and switch the login on/off to match.

    Returns an error message, or None when it worked.
    """
    if new_status not in STATUS_TRANSITIONS.get(student["status"], ()):
        return f"A {student['status']} student cannot be changed to {new_status}."
    if new_status in LOGIN_OFF_STATUSES and student["active_assignments"]:
        return "This student is an active council officer. End the council assignment first."

    db = get_db()
    cursor = db.cursor()
    try:
        # "AND status = old" protects against two admins clicking at the same time
        cursor.execute("UPDATE students SET status = %s WHERE id = %s AND status = %s",
                       (new_status, student["id"], student["status"]))
        if cursor.rowcount != 1:
            db.rollback()
            return "The student was changed by someone else. Please refresh the page."
        cursor.execute("UPDATE users SET is_active = %s WHERE id = %s",
                       (0 if new_status in LOGIN_OFF_STATUSES else 1, student["user_id"]))

        if new_status == "archived":
            cursor.execute("INSERT INTO archives (entity_type, entity_id, reason, archived_by) "
                           "VALUES ('student', %s, %s, %s)",
                           (student["id"], f"Student {student['student_number']} archived", actor_id))
        elif student["status"] == "archived":
            cursor.execute("UPDATE archives SET restored_by = %s, restored_at = NOW() "
                           "WHERE entity_type = 'student' AND entity_id = %s AND restored_at IS NULL",
                           (actor_id, student["id"]))

        log_action(actor_id, "student_status_changed", "students",
                   f"Student {student['student_number']}: {student['status']} -> {new_status}",
                   affected_record=f"student:{student['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def reset_student_password(student, password_hash, actor_id):
    """Reuses the Phase 4A reset: new hashed password, forced change, lockout cleared."""
    reset_user_password(
        {"id": student["user_id"], "username": student["username"]}, password_hash, actor_id)
