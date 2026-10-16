import re
from datetime import date

import mysql.connector

from app.audit.services import log_action
from app.db import fetch_all, fetch_one, get_db

NAME_RE = re.compile(r"^(\d{4})-(\d{4})$")

# action -> (statuses it may start from, status it leads to)
TRANSITIONS = {
    "activate": (("upcoming", "closed"), "active"),
    "close":    (("active",), "closed"),
    "archive":  (("closed",), "archived"),
    "restore":  (("archived",), "closed"),
}
# Elections in these states block closing the year (voting is still going on or about to)
OPEN_STATES = ("open", "scheduled")
# Elections in these states block archiving the year (results are not final yet)
UNFINISHED_STATES = ("open", "scheduled", "closed", "pending_verification", "verified")
AUDIT_ACTIONS = {"activate": "school_year_activated", "close": "school_year_closed",
                 "archive": "school_year_archived", "restore": "school_year_restored"}


def list_school_years():
    return fetch_all(
        "SELECT sy.id, sy.name, sy.start_date, sy.end_date, sy.status, "
        "  (SELECT COUNT(*) FROM students s WHERE s.school_year_id = sy.id) AS student_count, "
        "  (SELECT COUNT(*) FROM elections e WHERE e.school_year_id = sy.id) AS election_count "
        "FROM school_years sy ORDER BY sy.start_date DESC, sy.id DESC"
    )


def get_school_year(year_id):
    return fetch_one("SELECT id, name, start_date, end_date, status FROM school_years WHERE id = %s", (year_id,))


def validate_school_year(form, year_id=None):
    """form: name, start_date, end_date (all text). Returns a list of error messages."""
    errors = []
    match = NAME_RE.match(form["name"])
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        errors.append("Name must look like 2026-2027 (the second year is one more than the first).")
    elif fetch_one("SELECT id FROM school_years WHERE name = %s AND id <> %s", (form["name"], year_id or 0)):
        errors.append("That school year already exists.")

    try:
        start = date.fromisoformat(form["start_date"])
        end = date.fromisoformat(form["end_date"])
    except ValueError:
        errors.append("Please enter a valid start date and end date.")
    else:
        if end <= start:
            errors.append("The end date must be after the start date.")
    return errors


def create_school_year(form, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("INSERT INTO school_years (name, start_date, end_date, status) VALUES (%s, %s, %s, 'upcoming')",
                       (form["name"], form["start_date"], form["end_date"]))
        new_id = cursor.lastrowid
        log_action(actor_id, "school_year_created", "school_years", f"Created school year {form['name']}",
                   affected_record=f"school_year:{new_id}", commit=False)
        db.commit()
        return new_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def update_school_year(year, form, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE school_years SET name = %s, start_date = %s, end_date = %s WHERE id = %s",
                       (form["name"], form["start_date"], form["end_date"], year["id"]))
        log_action(actor_id, "school_year_updated", "school_years", f"Updated school year {year['name']}",
                   affected_record=f"school_year:{year['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def _count_elections(year_id, statuses):
    placeholders = ", ".join(["%s"] * len(statuses))
    row = fetch_one(f"SELECT COUNT(*) AS n FROM elections WHERE school_year_id = %s AND status IN ({placeholders})",
                    (year_id,) + tuple(statuses))
    return row["n"]


def change_status(year, action, actor_id):
    """Apply one status change. Returns an error message, or None when it worked."""
    allowed_from, new_status = TRANSITIONS[action]
    if year["status"] not in allowed_from:
        return f"A {year['status']} school year cannot be changed this way."

    if action == "activate":
        other = fetch_one("SELECT name FROM school_years WHERE status = 'active' AND id <> %s", (year["id"],))
        if other:
            return f"School year {other['name']} is still active. Close it first."
    elif action == "close" and _count_elections(year["id"], OPEN_STATES):
        return "This school year has an open or scheduled election. Close the election first."
    elif action == "archive" and _count_elections(year["id"], UNFINISHED_STATES):
        return "This school year has elections that are not finished (results not published or archived)."

    db = get_db()
    cursor = db.cursor()
    try:
        # "AND status = old" protects against two admins clicking at the same time
        cursor.execute("UPDATE school_years SET status = %s WHERE id = %s AND status = %s",
                       (new_status, year["id"], year["status"]))
        if cursor.rowcount != 1:
            db.rollback()
            return "The school year was changed by someone else. Please refresh the page."

        if action == "archive":
            cursor.execute("INSERT INTO archives (entity_type, entity_id, reason, archived_by) "
                           "VALUES ('school_year', %s, %s, %s)",
                           (year["id"], f"School year {year['name']} archived", actor_id))
        elif action == "restore":
            cursor.execute("UPDATE archives SET restored_by = %s, restored_at = NOW() "
                           "WHERE entity_type = 'school_year' AND entity_id = %s AND restored_at IS NULL",
                           (actor_id, year["id"]))

        log_action(actor_id, AUDIT_ACTIONS[action], "school_years",
                   f"School year {year['name']}: {year['status']} -> {new_status}",
                   affected_record=f"school_year:{year['id']}", commit=False)
        db.commit()
        return None
    except mysql.connector.IntegrityError:
        db.rollback()
        return "Only one school year can be active at a time."
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
