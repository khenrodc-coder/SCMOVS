from app.audit.services import log_action
from app.db import fetch_all, fetch_one, get_db
from app.settings.services import get_bool
from app.utils import escape_like, get_page, to_int

PER_PAGE = 10
STATUSES = ("pending", "approved", "rejected", "disqualified")
# Candidates can be registered and edited only while the election is in one of these statuses
REGISTRATION_STATUSES = ("draft", "scheduled")

# action -> (statuses it may start from, new status, election statuses where it is allowed)
REVIEW_ACTIONS = {
    "approve":    (("pending",), "approved", ("draft", "scheduled")),
    "reject":     (("pending",), "rejected", ("draft", "scheduled")),
    "disqualify": (("pending", "approved"), "disqualified", ("draft", "scheduled", "open")),
    "reopen":     (("rejected",), "pending", ("draft", "scheduled")),
}
NEEDS_REMARKS = ("reject", "disqualify")
AUDIT_ACTIONS = {"approve": "candidate_approved", "reject": "candidate_rejected",
                 "disqualify": "candidate_disqualified", "reopen": "candidate_reopened"}
PAST = {"approve": "approved", "reject": "rejected",
        "disqualify": "disqualified", "reopen": "moved back to pending"}


# ================================================================ lookups

def get_election(election_id):
    return fetch_one(
        "SELECT e.id, e.name, e.status, e.department_id, e.school_year_id, d.name AS department, sy.name AS school_year "
        "FROM elections e JOIN departments d ON d.id = e.department_id "
        "JOIN school_years sy ON sy.id = e.school_year_id WHERE e.id = %s", (election_id,))


def get_registrable_elections():
    """Elections that still accept candidate registrations."""
    return fetch_all(
        "SELECT e.id, e.name, d.name AS department, sy.name AS school_year FROM elections e "
        "JOIN departments d ON d.id = e.department_id JOIN school_years sy ON sy.id = e.school_year_id "
        "WHERE e.status IN ('draft', 'scheduled') ORDER BY e.start_at DESC")


def get_election_positions(election_id):
    return fetch_all("SELECT p.id, p.name FROM election_positions ep JOIN positions p ON p.id = ep.position_id "
                     "WHERE ep.election_id = %s ORDER BY ep.display_order, ep.id", (election_id,))


def get_filter_options():
    return {
        "elections": fetch_all("SELECT id, name FROM elections WHERE status <> 'archived' ORDER BY start_at DESC"),
        "positions": fetch_all("SELECT id, name FROM positions ORDER BY display_order, id"),
    }


# ==================================================================== list

def list_candidates(args):
    q = args.get("q", "").strip()[:100]
    election = to_int(args.get("election"))
    position = to_int(args.get("position"))
    status = args.get("status", "")
    if status not in STATUSES:
        status = ""

    where, params = [], []
    if q:
        like = "%" + escape_like(q) + "%"
        where.append("(s.student_number LIKE %s OR s.first_name LIKE %s OR s.last_name LIKE %s "
                     "OR CONCAT_WS(' ', s.first_name, s.last_name) LIKE %s)")
        params.extend([like] * 4)
    if election:
        where.append("c.election_id = %s")
        params.append(election)
    else:
        where.append("e.status <> 'archived'")
    if position:
        where.append("c.position_id = %s")
        params.append(position)
    if status:
        where.append("c.status = %s")
        params.append(status)
    where_sql = "WHERE " + " AND ".join(where)

    joins = ("FROM candidates c JOIN students s ON s.id = c.student_id JOIN elections e ON e.id = c.election_id "
             "JOIN positions p ON p.id = c.position_id "
             "JOIN election_positions ep ON ep.election_id = c.election_id AND ep.position_id = c.position_id ")
    total = fetch_one("SELECT COUNT(*) AS n " + joins +
                      where_sql, tuple(params))["n"]
    page, pages = get_page(args, total, PER_PAGE)

    candidates = fetch_all(
        "SELECT c.id, c.status, c.photo_path, s.student_number, s.first_name, s.last_name, p.name AS position_name, "
        "       e.id AS election_id, e.name AS election_name, e.status AS election_status "
        + joins + where_sql +
        " ORDER BY e.start_at DESC, e.id DESC, ep.display_order, s.last_name, s.first_name LIMIT %s OFFSET %s",
        tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE))

    base_filters = {k: v for k, v in (
        ("q", q), ("election", election), ("position", position), ("status", status)) if v}
    return {"candidates": candidates, "q": q, "election": election, "position": position, "status": status,
            "page": page, "pages": pages, "total": total, "base_filters": base_filters}


def get_candidate(candidate_id):
    return fetch_one(
        "SELECT c.id, c.election_id, c.student_id, c.position_id, c.platform, c.photo_path, c.status, c.remarks, "
        "       c.reviewed_at, c.created_at, rv.full_name AS reviewed_by_name, "
        "       s.student_number, s.first_name, s.middle_name, s.last_name, s.user_id, s.year_level, s.section, "
        "       d.name AS department, p.name AS position_name, "
        "       e.name AS election_name, e.status AS election_status "
        "FROM candidates c JOIN students s ON s.id = c.student_id JOIN elections e ON e.id = c.election_id "
        "JOIN departments d ON d.id = s.department_id JOIN positions p ON p.id = c.position_id "
        "LEFT JOIN users rv ON rv.id = c.reviewed_by WHERE c.id = %s", (candidate_id,))


# ========================================================== registration

def find_student_for_election(election, student_number):
    """Return (student, None) if the student may run in this election, else (None, reason)."""
    student = fetch_one(
        "SELECT id, student_number, first_name, last_name, department_id, school_year_id, status "
        "FROM students WHERE student_number = %s", (student_number,))
    if student is None:
        return None, "No student has that Student ID."
    if student["status"] != "active":
        return None, "That student is not active."
    if student["department_id"] != election["department_id"]:
        return None, f"That student is not in the {election['department']} department of this election."
    if student["school_year_id"] != election["school_year_id"]:
        return None, f"That student is not enrolled in school year {election['school_year']}."
    if fetch_one("SELECT id FROM candidates WHERE election_id = %s AND student_id = %s",
                 (election["id"], student["id"])):
        return None, "That student is already registered as a candidate in this election."
    return student, None


def validate_platform(platform):
    return ["The platform text must be 2000 characters or fewer."] if len(platform) > 2000 else []


def valid_position(election_id, position_id):
    return position_id is not None and fetch_one(
        "SELECT position_id FROM election_positions WHERE election_id = %s AND position_id = %s",
        (election_id, position_id)) is not None


def register_candidate(election, student, position_id, platform, actor_id, photo_path=None):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO candidates (election_id, student_id, position_id, platform, photo_path, status, created_by) "
            "VALUES (%s, %s, %s, %s, %s, 'pending', %s)",
            (election["id"], student["id"], position_id, platform or None, photo_path, actor_id))
        new_id = cursor.lastrowid
        log_action(actor_id, "candidate_registered", "candidates",
                   f"Registered candidate {student['student_number']} in '{election['name']}'",
                   affected_record=f"candidate:{new_id}", commit=False)
        db.commit()
        return new_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def update_candidate(candidate, position_id, platform, actor_id, photo_path=None):
    """Edit position/platform. An approved candidate goes back to pending (needs a new review)."""
    reset = candidate["status"] == "approved"
    db = get_db()
    cursor = db.cursor()
    try:
        # photo_path None = keep the existing photo
        photo_sql, photo_args = ("", ()) if photo_path is None else (", photo_path = %s", (photo_path,))
        if reset:
            cursor.execute("UPDATE candidates SET position_id = %s, platform = %s, status = 'pending', "
                           "reviewed_by = NULL, reviewed_at = NULL, remarks = NULL" + photo_sql + " WHERE id = %s",
                           (position_id, platform or None) + photo_args + (candidate["id"],))
        else:
            cursor.execute("UPDATE candidates SET position_id = %s, platform = %s" + photo_sql + " WHERE id = %s",
                           (position_id, platform or None) + photo_args + (candidate["id"],))
        suffix = " (approval removed, needs a new review)" if reset else ""
        log_action(actor_id, "candidate_updated", "candidates",
                   f"Updated candidate {candidate['student_number']} in '{candidate['election_name']}'{suffix}",
                   affected_record=f"candidate:{candidate['id']}", commit=False)
        db.commit()
        return reset
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def can_edit(candidate):
    return candidate["election_status"] in REGISTRATION_STATUSES and candidate["status"] != "disqualified"


# ============================================================= review

def review(candidate, action, remarks, actor_id):
    """Approve, reject, disqualify or reopen a candidate. Returns an error message or None."""
    allowed_from, new_status, election_statuses = REVIEW_ACTIONS[action]
    if candidate["status"] not in allowed_from:
        return f"A {candidate['status']} candidate cannot be {PAST[action]}."
    if candidate["election_status"] not in election_statuses:
        return f"This cannot be done while the election is {candidate['election_status'].replace('_', ' ')}."
    if action in NEEDS_REMARKS and not remarks:
        return "Please write the reason (remarks) for this decision."
    if len(remarks) > 500:
        return "Remarks must be 500 characters or fewer."

    db = get_db()
    cursor = db.cursor()
    try:
        if action == "reopen":
            cursor.execute("UPDATE candidates SET status = 'pending', reviewed_by = NULL, reviewed_at = NULL, "
                           "remarks = NULL WHERE id = %s AND status = %s", (candidate["id"], candidate["status"]))
        else:
            cursor.execute("UPDATE candidates SET status = %s, remarks = %s, reviewed_by = %s, reviewed_at = NOW() "
                           "WHERE id = %s AND status = %s",
                           (new_status, remarks or None, actor_id, candidate["id"], candidate["status"]))
        if cursor.rowcount != 1:
            db.rollback()
            return "The candidate was changed by someone else. Please refresh the page."

        if action != "reopen" and get_bool("notifications_enabled", True):
            text = (f"Your candidacy for {candidate['position_name']} in '{candidate['election_name']}' was "
                    f"{PAST[action]}." + (f" Reason: {remarks}" if remarks else ""))
            cursor.execute("INSERT INTO notifications (user_id, title, message, related_module) "
                           "VALUES (%s, %s, %s, 'candidates')",
                           (candidate["user_id"], f"Candidacy {PAST[action]}", text[:500]))

        log_action(actor_id, AUDIT_ACTIONS[action], "candidates",
                   f"Candidate {candidate['student_number']} for {candidate['position_name']} in "
                   f"'{candidate['election_name']}': {candidate['status']} -> {new_status}",
                   affected_record=f"candidate:{candidate['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


# ============================================================== photo only
PHOTO_ELECTION_STATUSES = ("draft", "scheduled", "open")


def can_change_photo(candidate):
    """A photo can be replaced on its own until the election closes. It never changes approval or eligibility."""
    return candidate["election_status"] in PHOTO_ELECTION_STATUSES


def update_photo(candidate, photo_path, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE candidates SET photo_path = %s WHERE id = %s", (photo_path, candidate["id"]))
        log_action(actor_id, "candidate_photo_changed", "candidates",
                   f"Changed photo of candidate {candidate['student_number']} in '{candidate['election_name']}'",
                   affected_record=f"candidate:{candidate['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def student_summary(election, student_number):
    """For the registration modal: names and department of the student, or the reason they cannot run."""
    student, problem = find_student_for_election(election, student_number)
    if problem:
        return None, problem
    full = fetch_one("SELECT s.first_name, s.middle_name, s.last_name, d.name AS department "
                     "FROM students s JOIN departments d ON d.id = s.department_id WHERE s.id = %s", (student["id"],))
    return full, None
