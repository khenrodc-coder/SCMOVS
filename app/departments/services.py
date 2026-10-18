import re

from app.audit.services import log_action
from app.db import fetch_all, fetch_one, get_db

CODE_RE = re.compile(r"^[A-Z0-9]{2,10}$")
# A department with an election in one of these states cannot be deactivated
BUSY_ELECTION_STATUSES = ("open", "scheduled")


def list_departments():
    return fetch_all(
        "SELECT d.id, d.name, d.code, d.is_active, "
        "  (SELECT COUNT(*) FROM students s WHERE s.department_id = d.id AND s.status <> 'archived') AS student_count, "
        "  (SELECT COUNT(*) FROM elections e WHERE e.department_id = d.id) AS election_count "
        "FROM departments d ORDER BY d.id"
    )


def get_department(department_id):
    return fetch_one("SELECT id, name, code, is_active FROM departments WHERE id = %s", (department_id,))


def validate_department(form, department_id=None):
    """Return {field: message} (empty = valid). form: name, code (already upper-case)."""
    errors = {}
    if not 2 <= len(form["name"]) <= 60:
        errors["name"] = "Department name must be between 2 and 60 characters."
    elif fetch_one("SELECT id FROM departments WHERE name = %s AND id <> %s", (form["name"], department_id or 0)):
        errors["name"] = "A department with that name already exists."

    if not CODE_RE.match(form["code"]):
        errors["code"] = "Code must be 2-10 characters: capital letters and numbers only (example: COL)."
    elif fetch_one("SELECT id FROM departments WHERE code = %s AND id <> %s", (form["code"], department_id or 0)):
        errors["code"] = "That department code is already used."
    return errors


def create_department(form, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("INSERT INTO departments (name, code) VALUES (%s, %s)", (form["name"], form["code"]))
        new_id = cursor.lastrowid
        log_action(actor_id, "department_created", "departments",
                   f"Created department '{form['name']}' ({form['code']})",
                   affected_record=f"department:{new_id}", commit=False)
        db.commit()
        return new_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def update_department(department, form, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE departments SET name = %s, code = %s WHERE id = %s",
                       (form["name"], form["code"], department["id"]))
        log_action(actor_id, "department_updated", "departments",
                   f"Updated department '{department['name']}'",
                   affected_record=f"department:{department['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def set_department_active(department, active, actor_id):
    """Return an error message if the change is not allowed, otherwise None."""
    if not active:
        placeholders = ", ".join(["%s"] * len(BUSY_ELECTION_STATUSES))
        busy = fetch_one(
            f"SELECT COUNT(*) AS n FROM elections WHERE department_id = %s AND status IN ({placeholders})",
            (department["id"],) + BUSY_ELECTION_STATUSES)
        if busy["n"]:
            return "This department has an open or scheduled election. Close or cancel it first."

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE departments SET is_active = %s WHERE id = %s", (1 if active else 0, department["id"]))
        log_action(actor_id, "department_activated" if active else "department_deactivated", "departments",
                   f"{'Activated' if active else 'Deactivated'} department '{department['name']}'",
                   affected_record=f"department:{department['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
