from datetime import datetime
from flask import url_for
from app.audit.services import log_action
from app.db import fetch_all, fetch_one, get_db
from app.settings.services import get_bool
from app.utils import escape_like, get_page, to_int

PER_PAGE = 10
# the format of <input type="datetime-local">
DT_FORMAT = "%Y-%m-%dT%H:%M"
STATUSES = ("draft", "scheduled", "open", "closed",
            "pending_verification", "verified", "published", "archived")

# Positions and dates can only be changed in these statuses
EDITABLE = ("draft", "scheduled")

# action -> (statuses it may start from, status it leads to)
# Results verification and publishing (pending_verification -> verified -> published) come in Phase 5.
ACTIONS = {
    "schedule":   (("draft",), "scheduled"),
    "unschedule": (("scheduled",), "draft"),
    "open":       (("scheduled",), "open"),
    "close":      (("open",), "closed"),
    "archive":    (("draft",), "archived"),
    # goes back to draft (or published if it was published)
    "restore":    (("archived",), None),
}
AUDIT_ACTIONS = {"schedule": "election_scheduled", "unschedule": "election_unscheduled",
                 "open": "election_opened", "close": "election_closed",
                 "archive": "election_archived", "restore": "election_restored"}


def db_now():
    """The database clock. The voting triggers use it too, so we compare against the same clock."""
    return fetch_one("SELECT NOW() AS now")["now"]


def parse_dt(text):
    for fmt in (DT_FORMAT, "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


# ================================================================ lookups

def get_form_options(election=None):
    """Departments and school years for the form (the current ones stay selectable when editing)."""
    departments = fetch_all(
        "SELECT id, name FROM departments WHERE is_active = 1 ORDER BY id")
    years = fetch_all(
        "SELECT id, name FROM school_years WHERE status IN ('active', 'upcoming') ORDER BY start_date DESC")
    if election is not None:
        if not any(d["id"] == election["department_id"] for d in departments):
            departments.append(
                {"id": election["department_id"], "name": election["department"] + " (inactive)"})
        if not any(y["id"] == election["school_year_id"] for y in years):
            years.append(
                {"id": election["school_year_id"], "name": election["school_year"]})
    return departments, years


def get_filter_options():
    return {
        "departments": fetch_all("SELECT id, name FROM departments ORDER BY id"),
        "school_years": fetch_all("SELECT id, name FROM school_years ORDER BY start_date DESC"),
    }


# ==================================================================== list

def list_elections(args):
    q = args.get("q", "").strip()[:100]
    department = to_int(args.get("department"))
    school_year = to_int(args.get("school_year"))
    status = args.get("status", "")
    if status not in STATUSES:
        status = ""

    where, params = [], []
    if q:
        where.append("e.name LIKE %s")
        params.append("%" + escape_like(q) + "%")
    if department:
        where.append("e.department_id = %s")
        params.append(department)
    if school_year:
        where.append("e.school_year_id = %s")
        params.append(school_year)
    if status:
        where.append("e.status = %s")
        params.append(status)
    else:
        where.append("e.status <> 'archived'")
    where_sql = "WHERE " + " AND ".join(where)

    total = fetch_one("SELECT COUNT(*) AS n FROM elections e " +
                      where_sql, tuple(params))["n"]
    page, pages = get_page(args, total, PER_PAGE)

    elections = fetch_all(
        "SELECT e.id, e.name, e.status, e.start_at, e.end_at, d.name AS department, sy.name AS school_year, "
        "  (SELECT COUNT(*) FROM election_positions ep WHERE ep.election_id = e.id) AS position_count, "
        "  (SELECT COUNT(*) FROM candidates c WHERE c.election_id = e.id) AS candidate_count, "
        "  (SELECT COUNT(*) FROM candidates c WHERE c.election_id = e.id AND c.status = 'approved') AS approved_count, "
        "  (e.status = 'open' AND e.end_at < NOW()) AS overdue "
        "FROM elections e JOIN departments d ON d.id = e.department_id "
        "JOIN school_years sy ON sy.id = e.school_year_id "
        + where_sql + " ORDER BY e.start_at DESC, e.id DESC LIMIT %s OFFSET %s",
        tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE))

    base_filters = {k: v for k, v in (("q", q), ("department", department),
                                      ("school_year", school_year), ("status", status)) if v}
    return {"elections": elections, "q": q, "department": department, "school_year": school_year,
            "status": status, "page": page, "pages": pages, "total": total, "base_filters": base_filters}


def get_election(election_id):
    return fetch_one(
        "SELECT e.id, e.name, e.status, e.start_at, e.end_at, e.department_id, e.school_year_id, e.published_at, "
        "       d.name AS department, d.code AS department_code, sy.name AS school_year, sy.status AS school_year_status, "
        "       (SELECT COUNT(*) FROM candidates c WHERE c.election_id = e.id) AS candidate_count, "
        "       (SELECT COUNT(*) FROM election_positions ep WHERE ep.election_id = e.id) AS position_count, "
        "       (e.status = 'open' AND e.end_at < NOW()) AS overdue "
        "FROM elections e JOIN departments d ON d.id = e.department_id "
        "JOIN school_years sy ON sy.id = e.school_year_id WHERE e.id = %s",
        (election_id,))


def get_participation(election_id):
    """Counts only (from the aggregate view). Never who voted for whom."""
    row = fetch_one("SELECT eligible_voters, votes_cast FROM v_election_participation WHERE election_id = %s",
                    (election_id,))
    eligible, cast = int(row["eligible_voters"]), int(row["votes_cast"])
    return {"eligible": eligible, "cast": cast, "percent": round(cast * 100 / eligible, 1) if eligible else 0}


# ============================================================ validation

def validate_election(form, locked=False):
    """Return a list of error messages. If locked, department and school year are not checked."""
    errors = []
    if not 3 <= len(form["name"]) <= 150:
        errors.append("Election name must be between 3 and 150 characters.")

    if not locked:
        department_id = to_int(form["department_id"])
        if department_id is None or not fetch_one(
                "SELECT id FROM departments WHERE id = %s AND is_active = 1", (department_id,)):
            errors.append("Please choose an active department.")
        year_id = to_int(form["school_year_id"])
        if year_id is None or not fetch_one(
                "SELECT id FROM school_years WHERE id = %s AND status IN ('active', 'upcoming')", (year_id,)):
            errors.append("Please choose an active or upcoming school year.")

    start, end = parse_dt(form["start_at"]), parse_dt(form["end_at"])
    if start is None or end is None:
        errors.append("Please enter a valid start and end date/time.")
    elif end <= start:
        errors.append("The end must be after the start.")
    elif end <= db_now():
        errors.append("The end date/time must be in the future.")
    return errors


# ============================================================== changes
# Each change and its audit log entry are saved in ONE transaction.

def create_election(form, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO elections (name, department_id, school_year_id, start_at, end_at, status, created_by) "
            "VALUES (%s, %s, %s, %s, %s, 'draft', %s)",
            (form["name"], int(form["department_id"]), int(form["school_year_id"]),
             parse_dt(form["start_at"]), parse_dt(form["end_at"]), actor_id))
        new_id = cursor.lastrowid
        log_action(actor_id, "election_created", "elections", f"Created election '{form['name']}'",
                   affected_record=f"election:{new_id}", commit=False)
        db.commit()
        return new_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def update_election(election, form, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE elections SET name = %s, department_id = %s, school_year_id = %s, start_at = %s, end_at = %s "
            "WHERE id = %s AND status IN ('draft', 'scheduled')",
            (form["name"], int(form["department_id"]), int(form["school_year_id"]),
             parse_dt(form["start_at"]), parse_dt(form["end_at"]), election["id"]))
        log_action(actor_id, "election_updated", "elections", f"Updated election '{election['name']}'",
                   affected_record=f"election:{election['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


# ------------------------------------------------------------ positions

def get_election_positions(election_id):
    return fetch_all(
        "SELECT ep.position_id, p.name, ep.display_order, COUNT(c.id) AS total, "
        "       COALESCE(SUM(c.status = 'approved'), 0) AS approved, "
        "       COALESCE(SUM(c.status = 'pending'), 0) AS pending "
        "FROM election_positions ep JOIN positions p ON p.id = ep.position_id "
        "LEFT JOIN candidates c ON c.election_id = ep.election_id AND c.position_id = ep.position_id "
        "WHERE ep.election_id = %s GROUP BY ep.id, ep.position_id, p.name, ep.display_order "
        "ORDER BY ep.display_order, ep.id",
        (election_id,))


def get_available_positions(election_id):
    return fetch_all(
        "SELECT p.id, p.name FROM positions p WHERE p.is_active = 1 "
        "AND p.id NOT IN (SELECT position_id FROM election_positions WHERE election_id = %s) "
        "ORDER BY p.display_order, p.id", (election_id,))


def _positions_locked(election):
    if election["status"] not in EDITABLE:
        return "Positions can only be changed while the election is a draft or scheduled."
    return None


def add_positions(election, raw_ids, actor_id):
    """Add the chosen active positions to the election. Returns an error message or None."""
    problem = _positions_locked(election)
    if problem:
        return problem
    wanted = {i for i in (to_int(x) for x in raw_ids) if i}
    if not wanted:
        return "Please select at least one position."

    available = {row["id"]: row["name"]
                 for row in get_available_positions(election["id"])}
    # keeps the default position order
    chosen = [pid for pid in available if pid in wanted]
    if not chosen:
        return "Those positions are not available (inactive or already added)."

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SELECT COALESCE(MAX(display_order), 0) FROM election_positions WHERE election_id = %s",
                       (election["id"],))
        order = cursor.fetchone()[0]
        for position_id in chosen:
            order += 1
            cursor.execute("INSERT INTO election_positions (election_id, position_id, display_order) "
                           "VALUES (%s, %s, %s)", (election["id"], position_id, order))
        names = ", ".join(available[pid] for pid in chosen)
        log_action(actor_id, "election_positions_added", "elections",
                   f"Added positions to '{election['name']}': {names}",
                   affected_record=f"election:{election['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def remove_position(election, position_id, actor_id):
    problem = _positions_locked(election)
    if problem:
        return problem
    row = fetch_one("SELECT p.name, (SELECT COUNT(*) FROM candidates c WHERE c.election_id = %s AND c.position_id = %s) AS n "
                    "FROM election_positions ep JOIN positions p ON p.id = ep.position_id "
                    "WHERE ep.election_id = %s AND ep.position_id = %s",
                    (election["id"], position_id, election["id"], position_id))
    if row is None:
        return "That position is not part of this election."
    if row["n"]:
        return "This position has candidates. Remove or move the candidates first."

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM election_positions WHERE election_id = %s AND position_id = %s",
                       (election["id"], position_id))
        _renumber(cursor, election["id"])
        log_action(actor_id, "election_position_removed", "elections",
                   f"Removed position '{row['name']}' from '{election['name']}'",
                   affected_record=f"election:{election['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def _renumber(cursor, election_id, ordered_ids=None):
    """Number the election's positions 1, 2, 3... in the given order (or the current order)."""
    if ordered_ids is None:
        cursor.execute("SELECT position_id FROM election_positions WHERE election_id = %s "
                       "ORDER BY display_order, id", (election_id,))
        ordered_ids = [row[0] for row in cursor.fetchall()]
    for number, position_id in enumerate(ordered_ids, start=1):
        cursor.execute("UPDATE election_positions SET display_order = %s WHERE election_id = %s AND position_id = %s",
                       (number, election_id, position_id))


def move_position(election, position_id, direction, actor_id):
    """Move a position up/down on this election's ballot. Returns an error message or None."""
    problem = _positions_locked(election)
    if problem:
        return problem
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SELECT position_id FROM election_positions WHERE election_id = %s "
                       "ORDER BY display_order, id FOR UPDATE", (election["id"],))
        ids = [row[0] for row in cursor.fetchall()]
        if position_id not in ids:
            db.rollback()
            return "That position is not part of this election."
        index = ids.index(position_id)
        target = index - 1 if direction == "up" else index + 1
        if target < 0 or target >= len(ids):
            db.rollback()
            return None                                    # already at the edge: nothing to do
        ids[index], ids[target] = ids[target], ids[index]
        _renumber(cursor, election["id"], ids)
        log_action(actor_id, "election_position_moved", "elections",
                   f"Reordered positions of '{election['name']}'",
                   affected_record=f"election:{election['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


# -------------------------------------------------------- status changes

def _ballot_blockers(election):
    """Reasons why this election is not ready to open. Empty list = ready."""
    problems = []
    rows = get_election_positions(election["id"])
    if not rows:
        problems.append("The election has no positions.")
    missing = [r["name"] for r in rows if int(r["approved"]) == 0]
    if missing and get_bool("election_require_candidate_per_position", True):
        problems.append("No approved candidate yet for: " +
                        ", ".join(missing) + ".")
    pending = sum(int(r["pending"]) for r in rows)
    if pending and get_bool("election_block_pending_candidates", True):
        problems.append(
            f"{pending} candidate(s) are still pending review. Approve or reject them first.")
    gone = fetch_all(
        "SELECT s.student_number FROM candidates c JOIN students s ON s.id = c.student_id "
        "WHERE c.election_id = %s AND c.status = 'approved' AND s.status <> 'active'", (election["id"],))
    if gone:
        problems.append("Approved candidates who are no longer active students: "
                        + ", ".join(r["student_number"] for r in gone) + ".")
    return problems


def _overlap(election):
    return fetch_one(
        "SELECT name FROM elections WHERE department_id = %s AND id <> %s AND status IN ('scheduled', 'open') "
        "AND start_at < %s AND end_at > %s LIMIT 1",
        (election["department_id"], election["id"], election["end_at"], election["start_at"]))


def _notify_eligible_students(cursor, election, title, message, link_url=None):
    """One in-app notification for every active student who can vote in this election."""
    if not get_bool("notifications_enabled", True):          # Settings -> Notifications
        return
    cursor.execute(
        "INSERT INTO notifications (user_id, title, message, related_module, link_url) "
        "SELECT s.user_id, %s, %s, 'elections', %s FROM students s JOIN users u ON u.id = s.user_id "
        "WHERE s.department_id = %s AND s.school_year_id = %s AND s.status = 'active' AND u.is_active = 1",
        (title[:150], message[:500], link_url, election["department_id"], election["school_year_id"]))


def _notify_admins(cursor, election, title, message, link_url):
    """Tell Super Admins and School Admins that voting opened/closed. Never inserts the same notice twice."""
    if not get_bool("notifications_enabled", True):
        return
    cursor.execute(
        "INSERT INTO notifications (user_id, title, message, related_module, link_url) "
        "SELECT u.id, %s, %s, 'elections', %s FROM users u JOIN roles r ON r.id = u.role_id "
        "WHERE r.name IN ('super_admin', 'school_admin') AND u.is_active = 1 "
        "AND NOT EXISTS (SELECT 1 FROM notifications n WHERE n.user_id = u.id AND n.title = %s AND n.link_url = %s)",
        (title[:150], message[:500], link_url, title[:150], link_url))


def change_status(election, action, actor_id):
    """Apply one status change. Returns an error message, or None when it worked."""
    allowed_from, new_status = ACTIONS[action]
    if election["status"] not in allowed_from:
        return f"A {election['status']} election cannot be changed this way."
    if action == "restore":
        new_status = "published" if election["published_at"] else "draft"

    if action in ("schedule", "open"):
        now = db_now()
        if election["end_at"] <= now:
            return "The end time has already passed. Edit the election dates first."
        clash = _overlap(election)
        if clash:
            return f"This period overlaps the election '{clash['name']}' of the same department."
        if action == "schedule" and election["position_count"] == 0:
            return "Add at least one position before scheduling the election."
        if action == "open":
            if election["start_at"] > now:
                return "The start time has not been reached yet. Edit the start time or wait."
            if election["school_year_status"] != "active":
                return "The school year of this election is not active."
            problems = _ballot_blockers(election)
            if problems:
                return " ".join(problems)

    db = get_db()
    cursor = db.cursor()
    try:
        # "AND status = old" protects against two admins clicking at the same time
        cursor.execute("UPDATE elections SET status = %s WHERE id = %s AND status = %s",
                       (new_status, election["id"], election["status"]))
        if cursor.rowcount != 1:
            db.rollback()
            return "The election was changed by someone else. Please refresh the page."

        if action in ("open", "close"):
            word = "opened" if action == "open" else "closed"
            _notify_admins(cursor, election, f"Voting {word}: {election['name']}"[:150],
                           f"Voting for '{election['name']}' has {word}.", url_for("elections.detail", election_id=election["id"]))
        if action == "open":
            _notify_eligible_students(cursor, election, "Voting is open",
                                      f"Voting for '{election['name']}' is now open until "
                                      f"{election['end_at']:%b %d, %Y %I:%M %p}.",
                                      url_for("voting.ballot", election_id=election["id"]))
        elif action == "close":
            _notify_eligible_students(cursor, election, "Voting is closed",
                                      f"Voting for '{election['name']}' has closed. Results will be announced after verification.",
                                      url_for("voting.my_elections"))
        elif action == "archive":
            cursor.execute("INSERT INTO archives (entity_type, entity_id, reason, archived_by) "
                           "VALUES ('election', %s, %s, %s)",
                           (election["id"], f"Election '{election['name']}' archived", actor_id))
        elif action == "restore":
            cursor.execute("UPDATE archives SET restored_by = %s, restored_at = NOW() "
                           "WHERE entity_type = 'election' AND entity_id = %s AND restored_at IS NULL",
                           (actor_id, election["id"]))

        log_action(actor_id, AUDIT_ACTIONS[action], "elections",
                   f"Election '{election['name']}': {election['status']} -> {new_status}",
                   affected_record=f"election:{election['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
