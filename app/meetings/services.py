"""Council meetings: schedule, attendance, minutes and attachments.

Rules enforced here:
  * Officers only touch meetings of THEIR active council. Super Admin may manage any active council.
  * A meeting can be edited only while it is 'scheduled'.
  * Attendance and minutes can only be recorded after the meeting has started, and never for a cancelled meeting.
  * 'Completed' needs the meeting to have started AND attendance to be recorded.
  * 'Cancelled' is only possible while no attendance has been recorded (the meeting did not happen).
  * Completed and cancelled meetings never go back to 'scheduled'.
"""
from datetime import datetime, timedelta

from app.audit.services import log_action
from app.auth.services import has_permission
from app.db import fetch_all, fetch_one, get_db
from app.documents import services as documents
from app.proposals.services import is_admin, my_councils, user_scope
from app.utils import escape_like, get_page, to_int

PER_PAGE = 10
STATUSES = ("scheduled", "completed", "cancelled")
ATTENDANCE_VALUES = ("present", "absent", "excused")
FORM_FIELDS = ("council_id", "title", "meeting_at", "location", "agenda")
# uploads/meetings/  (finance files live in uploads/finance/)
MANAGE_ROLES = ("super_admin", "council_officer")
STATUS_ACTIONS = {"complete": "completed", "cancel": "cancelled"}
# characters (the TEXT column holds 65,535 bytes, 4 bytes per character max)
MAX_MINUTES = 10000


# ================================================================ helpers

def db_now():
    """The database clock, so 'has the meeting started' uses the same time as meeting_at."""
    return fetch_one("SELECT NOW() AS n")["n"]


def _begin():
    """Start a fresh transaction (ends the read-only one opened by earlier SELECTs)."""
    db = get_db()
    db.rollback()
    db.start_transaction(isolation_level="READ COMMITTED")
    return db


def selectable_councils(user):
    if is_admin(user):
        return fetch_all("SELECT id, name FROM councils WHERE status = 'active' ORDER BY name")
    return my_councils(user["id"])


def can_manage(user, meeting):
    """Server-side: role + permission + council scope + council still active."""
    scope = user_scope(user)
    return (user["role"] in MANAGE_ROLES and has_permission("meetings.manage")
            and meeting["council_status"] == "active"
            and (scope is None or meeting["council_id"] in scope))


# ================================================================ reading

def get_meeting(meeting_id, user):
    """One meeting, or None if it does not exist or belongs to a council the user cannot see."""
    meeting = fetch_one(
        "SELECT m.*, (m.meeting_at <= NOW()) AS has_started, c.name AS council_name, c.status AS council_status, "
        "u.full_name AS created_by_name FROM meetings m JOIN councils c ON c.id = m.council_id "
        "JOIN users u ON u.id = m.created_by WHERE m.id = %s", (meeting_id,))
    if meeting is None:
        return None
    scope = user_scope(user)
    if scope is not None and meeting["council_id"] not in scope:
        return None
    return meeting


def list_meetings(args, user):
    q = args.get("q", "").strip()[:100]
    status = args.get("status", "")
    council = to_int(args.get("council"))
    date_from, date_to = _date(
        args.get("date_from")), _date(args.get("date_to"))

    where, params = ["1 = 1"], []
    if q:
        where.append("(m.title LIKE %s OR m.location LIKE %s)")
        params += ["%" + escape_like(q) + "%"] * 2
    scope = user_scope(user)
    if scope is None:
        if council:
            where.append("m.council_id = %s")
            params.append(council)
    elif not scope:
        where.append("1 = 0")
    else:
        where.append(f"m.council_id IN ({', '.join(['%s'] * len(scope))})")
        params += list(scope)
    if status in STATUSES:
        where.append("m.status = %s")
        params.append(status)
    else:
        status = ""
    if date_from:
        where.append("DATE(m.meeting_at) >= %s")
        params.append(date_from)
    if date_to:
        where.append("DATE(m.meeting_at) <= %s")
        params.append(date_to)

    where_sql = " AND ".join(where)
    total = fetch_one(
        f"SELECT COUNT(*) AS n FROM meetings m WHERE {where_sql}", tuple(params))["n"]
    page, pages = get_page(args, total, PER_PAGE)
    items = fetch_all(
        f"SELECT m.id, m.title, m.meeting_at, m.location, m.status, c.name AS council_name, "
        f"(SELECT COUNT(*) FROM meeting_attendance a WHERE a.meeting_id = m.id) AS attendance_count, "
        f"(SELECT COUNT(*) FROM meeting_minutes mm WHERE mm.meeting_id = m.id) AS has_minutes "
        f"FROM meetings m JOIN councils c ON c.id = m.council_id WHERE {where_sql} "
        f"ORDER BY m.meeting_at DESC, m.id DESC LIMIT %s OFFSET %s", tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE))
    filters = {k: v for k, v in (("q", q), ("status", status), ("council", council if scope is None else None),
                                 ("date_from", date_from.isoformat()
                                  if date_from else ""),
                                 ("date_to", date_to.isoformat() if date_to else "")) if v}
    return {"items": items, "page": page, "pages": pages, "total": total, "filters": filters, "q": q,
            "councils": fetch_all("SELECT id, name FROM councils ORDER BY name") if scope is None else []}


def _date(text):
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


ROSTER_SQL = (
    "SELECT co.id AS officer_id, u.full_name, p.name AS position_name, co.is_active, a.attendance "
    "FROM council_officers co JOIN users u ON u.id = co.user_id JOIN positions p ON p.id = co.position_id "
    "LEFT JOIN meeting_attendance a ON a.officer_id = co.id AND a.meeting_id = %s "
    "WHERE co.council_id = %s AND (co.is_active = 1 OR a.id IS NOT NULL) "
    "ORDER BY p.display_order, p.name, u.full_name")


def get_roster(meeting):
    """Active officers of the council, plus anyone who already has an attendance record for this meeting."""
    return fetch_all(ROSTER_SQL, (meeting["id"], meeting["council_id"]))


def get_minutes(meeting_id):
    return fetch_one("SELECT mm.content, mm.updated_at, u.full_name AS recorded_by_name FROM meeting_minutes mm "
                     "JOIN users u ON u.id = mm.recorded_by WHERE mm.meeting_id = %s", (meeting_id,))


def list_attachments(meeting_id):
    return fetch_all("SELECT d.id, d.title, d.original_filename, d.file_size, d.created_at, u.full_name AS uploaded_by_name "
                     "FROM documents d JOIN users u ON u.id = d.uploaded_by "
                     "WHERE d.meeting_id = %s AND d.is_archived = 0 ORDER BY d.created_at DESC", (meeting_id,))


def get_attachment(meeting_id, document_id):
    return fetch_one("SELECT * FROM documents WHERE id = %s AND meeting_id = %s AND is_archived = 0",
                     (document_id, meeting_id))


def detail_data(meeting, user):
    """Everything the detail page shows, including which buttons are allowed and WHY not."""
    roster = get_roster(meeting)
    recorded = sum(1 for r in roster if r["attendance"])
    summary = {
        v: sum(1 for r in roster if r["attendance"] == v) for v in ATTENDANCE_VALUES}
    manage = can_manage(user, meeting)
    open_status = meeting["status"] != "cancelled"
    scheduled = meeting["status"] == "scheduled"
    can_record = manage and open_status and bool(meeting["has_started"])

    # why a control is disabled (shown next to it)
    hints = {}
    if manage and open_status and not meeting["has_started"]:
        hints["record"] = "Attendance and minutes can be recorded once the meeting has started."
    if manage and scheduled:
        if not meeting["has_started"]:
            hints["complete"] = "A meeting can be completed only after it has started."
        elif recorded == 0:
            hints["complete"] = "Record attendance before marking the meeting as completed."
        if recorded > 0:
            hints["cancel"] = "A meeting with recorded attendance has already taken place and cannot be cancelled."
    return {
        "meeting": meeting, "roster": roster, "recorded": recorded, "summary": summary,
        "minutes": get_minutes(meeting["id"]), "attachments": list_attachments(meeting["id"]),
        "can_manage": manage, "can_edit": manage and scheduled, "can_record": can_record,
        "can_attach": manage and open_status,
        "can_complete": manage and scheduled and "complete" not in hints,
        "can_cancel": manage and scheduled and "cancel" not in hints,
        "hints": hints,
    }


# ================================================================ validation

def empty_form(council_id=""):
    return {"council_id": str(council_id), "title": "", "meeting_at": "", "location": "", "agenda": ""}


def form_from_meeting(meeting):
    return {"council_id": str(meeting["council_id"]), "title": meeting["title"],
            "meeting_at": meeting["meeting_at"].strftime("%Y-%m-%dT%H:%M"), "location": meeting["location"],
            "agenda": meeting["agenda"] or ""}


def validate_form(form, user, mode, meeting=None):
    """Return (errors, council_id, meeting_at). On edit the council cannot change."""
    errors = []
    if mode == "edit":
        council_id = meeting["council_id"]
    else:
        council_id = to_int(form["council_id"])
        if council_id not in [c["id"] for c in selectable_councils(user)]:
            errors.append("Please choose one of your active councils.")
            council_id = None

    if not 3 <= len(form["title"]) <= 200:
        errors.append("Title must be between 3 and 200 characters.")
    if not 2 <= len(form["location"]) <= 200:
        errors.append("Location must be between 2 and 200 characters.")
    if len(form["agenda"]) > 5000:
        errors.append("Agenda must be 5000 characters or fewer.")

    meeting_at = None
    try:
        meeting_at = datetime.strptime(form["meeting_at"], "%Y-%m-%dT%H:%M")
    except ValueError:
        errors.append("Please enter a valid meeting date and time.")
    if meeting_at:
        now = db_now()
        if not now - timedelta(days=730) <= meeting_at <= now + timedelta(days=730):
            errors.append("The meeting date must be within 2 years of today.")
        elif mode == "edit" and meeting_at > now:
            # Moving a meeting into the future after attendance/minutes exist would make those records impossible.
            has_records = fetch_one("SELECT (SELECT COUNT(*) FROM meeting_attendance WHERE meeting_id = %s) + "
                                    "(SELECT COUNT(*) FROM meeting_minutes WHERE meeting_id = %s) AS n",
                                    (meeting["id"], meeting["id"]))["n"]
            if has_records:
                errors.append(
                    "This meeting already has attendance or minutes, so it cannot be moved to the future.")
    return errors, council_id, meeting_at


# ================================================================ changes (each one is ONE transaction)

def create_meeting(form, council_id, meeting_at, user):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("INSERT INTO meetings (council_id, title, meeting_at, location, agenda, status, created_by) "
                       "VALUES (%s, %s, %s, %s, %s, 'scheduled', %s)",
                       (council_id, form["title"], meeting_at, form["location"], form["agenda"] or None, user["id"]))
        meeting_id = cursor.lastrowid
        log_action(user["id"], "meeting_created", "meetings", f"Scheduled meeting '{form['title']}' for {meeting_at:%Y-%m-%d %H:%M}",
                   affected_record=f"meeting:{meeting_id}", commit=False)
        db.commit()
        return meeting_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def _lock_meeting(cursor, meeting_id):
    """Lock the meeting row and read its CURRENT state (the page the user saw may be old)."""
    cursor.execute("SELECT status, council_id, title, (meeting_at <= NOW()) AS has_started "
                   "FROM meetings WHERE id = %s FOR UPDATE", (meeting_id,))
    return cursor.fetchone()


def update_meeting(meeting, form, meeting_at, user):
    """Returns an error message or None."""
    db = _begin()
    cursor = db.cursor(dictionary=True)
    try:
        locked = _lock_meeting(cursor, meeting["id"])
        if locked is None or locked["status"] != "scheduled":
            db.rollback()
            return "Only a scheduled meeting can be edited. Please refresh the page."
        cursor.execute("UPDATE meetings SET title = %s, meeting_at = %s, location = %s, agenda = %s WHERE id = %s",
                       (form["title"], meeting_at, form["location"], form["agenda"] or None, meeting["id"]))
        log_action(user["id"], "meeting_updated", "meetings", f"Updated meeting '{form['title']}'",
                   affected_record=f"meeting:{meeting['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def change_status(meeting, action, user):
    """complete / cancel. Returns an error message or None."""
    new_status = STATUS_ACTIONS[action]
    db = _begin()
    cursor = db.cursor(dictionary=True)
    try:
        locked = _lock_meeting(cursor, meeting["id"])
        if locked is None or locked["status"] != "scheduled":
            db.rollback()
            return f"A {meeting['status']} meeting cannot be changed to {new_status}."
        cursor.execute(
            "SELECT COUNT(*) AS n FROM meeting_attendance WHERE meeting_id = %s", (meeting["id"],))
        recorded = cursor.fetchone()["n"]
        if action == "complete" and (not locked["has_started"] or recorded == 0):
            db.rollback()
            return "To complete a meeting it must have started and its attendance must be recorded."
        if action == "cancel" and recorded > 0:
            db.rollback()
            return "A meeting with recorded attendance has already taken place and cannot be cancelled."
        cursor.execute(
            "UPDATE meetings SET status = %s WHERE id = %s", (new_status, meeting["id"]))
        log_action(user["id"], f"meeting_{new_status}", "meetings", f"Meeting '{meeting['title']}': scheduled -> {new_status}",
                   affected_record=f"meeting:{meeting['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def save_attendance(meeting, form, user):
    """Save present/absent/excused for EVERY officer in the roster. Returns an error message or None."""
    db = _begin()
    cursor = db.cursor(dictionary=True)
    try:
        locked = _lock_meeting(cursor, meeting["id"])
        if locked is None or locked["status"] == "cancelled" or not locked["has_started"]:
            db.rollback()
            return "Attendance can only be recorded for a meeting that has started and is not cancelled."

        cursor.execute(ROSTER_SQL, (meeting["id"], locked["council_id"]))
        roster = cursor.fetchall()
        if not roster:
            db.rollback()
            return "This council has no officers to record attendance for."
        values = {}
        for officer in roster:
            choice = form.get(f"att_{officer['officer_id']}", "")
            if choice not in ATTENDANCE_VALUES:
                db.rollback()
                return f"Please choose present, absent or excused for {officer['full_name']}."
            values[officer["officer_id"]] = choice

        existing = {officer["officer_id"]
                    for officer in roster if officer["attendance"]}
        for officer_id, choice in values.items():       # update old rows, insert new ones (works on MySQL and MariaDB)
            if officer_id in existing:
                cursor.execute("UPDATE meeting_attendance SET attendance = %s WHERE meeting_id = %s AND officer_id = %s",
                               (choice, meeting["id"], officer_id))
            else:
                cursor.execute("INSERT INTO meeting_attendance (meeting_id, officer_id, attendance) VALUES (%s, %s, %s)",
                               (meeting["id"], officer_id, choice))
        counts = {v: list(values.values()).count(v) for v in ATTENDANCE_VALUES}
        log_action(user["id"], "attendance_recorded", "meetings",
                   f"Attendance for '{locked['title']}': {counts['present']} present, {counts['absent']} absent, "
                   f"{counts['excused']} excused", affected_record=f"meeting:{meeting['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def save_minutes(meeting, content, user):
    """Create or update the minutes (one record per meeting). Returns an error message or None."""
    content = content.strip()
    if not 10 <= len(content) <= MAX_MINUTES:
        return f"Minutes must be between 10 and {MAX_MINUTES} characters."
    db = _begin()
    cursor = db.cursor(dictionary=True)
    try:
        locked = _lock_meeting(cursor, meeting["id"])
        if locked is None or locked["status"] == "cancelled" or not locked["has_started"]:
            db.rollback()
            return "Minutes can only be recorded for a meeting that has started and is not cancelled."
        cursor.execute(
            "SELECT id FROM meeting_minutes WHERE meeting_id = %s", (meeting["id"],))
        if cursor.fetchone():
            cursor.execute("UPDATE meeting_minutes SET content = %s, recorded_by = %s WHERE meeting_id = %s",
                           (content, user["id"], meeting["id"]))
            action = "minutes_updated"
        else:
            cursor.execute("INSERT INTO meeting_minutes (meeting_id, content, recorded_by) VALUES (%s, %s, %s)",
                           (meeting["id"], content, user["id"]))
            action = "minutes_created"
        # The audit log says THAT minutes were saved, never what they contain.
        log_action(user["id"], action, "meetings", f"Saved minutes of '{locked['title']}'",
                   affected_record=f"meeting:{meeting['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def add_attachment(meeting, title, file_info, user):
    """Record an already-validated upload (documents.prepare_upload) against the meeting.
    Returns an error message or None."""
    db = _begin()
    cursor = db.cursor(dictionary=True)
    try:
        locked = _lock_meeting(cursor, meeting["id"])
        if locked is None or locked["status"] == "cancelled":
            db.rollback()
            documents.discard(file_info)
            return "Files cannot be attached to a cancelled meeting."
        label = (title or file_info["original"])[:200]
        document_id = documents.add_document_row(cursor, file_info, label, user["id"], locked["council_id"],
                                                 meeting_id=meeting["id"])
        log_action(user["id"], "meeting_file_added", "meetings",
                   f"Attached '{file_info['original']}' to '{locked['title']}'",
                   affected_record=f"document:{document_id}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        documents.discard(file_info)
        raise
    finally:
        cursor.close()


def remove_attachment(meeting, document, user):
    """Hide the file (archive). The file stays on disk and in the database as history."""
    db = _begin()
    cursor = db.cursor(dictionary=True)
    try:
        locked = _lock_meeting(cursor, meeting["id"])
        if locked is None or locked["status"] == "cancelled":
            db.rollback()
            return "Files of a cancelled meeting cannot be changed."
        cursor.execute("UPDATE documents SET is_archived = 1 WHERE id = %s AND meeting_id = %s",
                       (document["id"], meeting["id"]))
        log_action(user["id"], "meeting_file_removed", "meetings",
                   f"Removed '{document['original_filename']}' from '{locked['title']}'",
                   affected_record=f"document:{document['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
