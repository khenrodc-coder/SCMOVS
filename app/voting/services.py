"""Student voting (Phase 7A).

BALLOT SECRECY RULES (keep them when you extend this module):
  1. Only THIS file writes to `ballots` and `votes`, and it is the only place that ever mentions both.
  2. A student's participation ("did I vote?") is read from `ballots` alone. Nothing ever reads which
     candidates a particular student chose, not even that student after submitting.
  3. The audit log says THAT a student voted in an election. It never contains a ballot id or a choice.
  4. Results (Phase 7B) must count rows in `votes` only, never join them to `ballots`.

SAFETY RULES enforced before the database is touched (the database triggers and the
UNIQUE(student_id, election_id) key enforce them again as the last line of defence):
  * the user is an active student with a student record
  * the election is in the student's department AND school year
  * the election is 'open' and the current time is inside its start/end window
  * the student has no ballot yet for this election
  * every chosen candidate is APPROVED and belongs to that election and position
  * the ballot and all its votes are written in ONE transaction: all or nothing
"""
import mysql.connector

from app.audit.services import log_action
from app.db import fetch_all, fetch_one, get_db

VISIBLE_STATUSES = ("scheduled", "open", "closed",
                    "pending_verification", "verified", "published")
# MySQL error number for "duplicate entry" (the UNIQUE ballot key)
DUPLICATE_KEY = 1062

STATE_LABELS = {
    "open": ("Voting is open", "green"),
    "voted": ("You have voted", "blue"),
    "upcoming": ("Upcoming", "slate"),
    "not_started": ("Voting has not started", "slate"),
    "ended": ("Voting period ended", "amber"),
    "closed": ("Voting closed", "slate"),
    "published": ("Results published", "blue"),
}


# ================================================================ student and election lookups

def get_student(user_id):
    """The student record of this user, or None (staff accounts have none)."""
    return fetch_one(
        "SELECT s.id, s.student_number, s.first_name, s.last_name, s.year_level, s.section, s.status, "
        "s.department_id, s.school_year_id, d.name AS department, sy.name AS school_year "
        "FROM students s JOIN departments d ON d.id = s.department_id "
        "JOIN school_years sy ON sy.id = s.school_year_id WHERE s.user_id = %s", (user_id,))


def get_voter(user):
    """Who is voting: a student (their record) or a Super Admin, or None for anyone else.

    A Super Admin has no student record. The currently deployed ballots schema does not
    support administrator ballots, so voting is safely disabled for this role until the schema
    and database triggers are updated together.
    """
    if user["role"] == "super_admin":
        return {"id": None, "kind": "admin", "user_id": user["id"], "status": "active", "student_number": None,
                "first_name": user["full_name"], "last_name": "", "department_id": None, "school_year_id": None,
                "department": "All departments", "school_year": "All school years", "year_level": "", "section": ""}
    student = get_student(user["id"])
    if student is not None:
        student["kind"] = "student"
        student["user_id"] = user["id"]
    return student


def get_election(election_id):
    return fetch_one(
        "SELECT e.id, e.name, e.department_id, e.school_year_id, e.status, e.start_at, e.end_at, "
        "(e.start_at <= NOW() AND e.end_at >= NOW()) AS in_window, (NOW() < e.start_at) AS not_started, "
        "(NOW() > e.end_at) AS ended FROM elections e WHERE e.id = %s", (election_id,))


def my_ballot(election_id, voter):
    """Return participation time without reading ballot choices."""
    if voter.get("kind") == "admin":
        # The current database schema does not support Super Admin ballots.
        return None

    return fetch_one(
        "SELECT submitted_at FROM ballots "
        "WHERE election_id = %s AND student_id = %s",
        (election_id, voter["id"])
    )


def access_problem(election, student):
    """Return None when this voter may access an election, otherwise a reason to deny access."""
    if election is None or election["status"] not in VISIBLE_STATUSES:
        return "missing"
    if student.get("kind") == "admin":
        return (
            "forbidden",
            "Super Admin voting is temporarily unavailable because the current database schema supports student ballots only."
        )
    if student["status"] != "active":
        return ("forbidden", "Only active students can take part in elections.")
    if election["department_id"] != student["department_id"] or election["school_year_id"] != student["school_year_id"]:
        return ("forbidden", "This election is not for your department and school year.")
    return None


def voting_state(election, voted):
    """One word describing what this student can do now."""
    if voted:
        return "voted"
    status = election["status"]
    if status == "scheduled":
        return "upcoming"
    if status == "open":
        if election["not_started"]:
            return "not_started"
        if election["ended"]:
            return "ended"
        return "open"
    return "published" if status == "published" else "closed"


def list_elections(student):
    """Elections this voter may take part in, with their own voting state."""
    marks = ", ".join(["%s"] * len(VISIBLE_STATUSES))

    if student.get("kind") == "admin":
        # The current Railway ballots table has no administrator-voter column.
        # Avoid joining against a column that does not exist.
        rows = fetch_all(
            "SELECT e.id, e.name, e.status, e.start_at, e.end_at, "
            "(NOW() < e.start_at) AS not_started, "
            "(NOW() > e.end_at) AS ended, "
            "TIMESTAMPDIFF(SECOND, NOW(), e.start_at) AS secs_to_start, "
            "TIMESTAMPDIFF(SECOND, NOW(), e.end_at) AS secs_to_end, "
            "NULL AS voted_at, d.name AS department_name "
            "FROM elections e "
            "JOIN departments d ON d.id = e.department_id "
            f"WHERE e.status IN ({marks}) "
            "ORDER BY e.start_at DESC, e.id DESC",
            VISIBLE_STATUSES
        )
    else:
        rows = fetch_all(
            "SELECT e.id, e.name, e.status, e.start_at, e.end_at, "
            "(NOW() < e.start_at) AS not_started, "
            "(NOW() > e.end_at) AS ended, "
            "TIMESTAMPDIFF(SECOND, NOW(), e.start_at) AS secs_to_start, "
            "TIMESTAMPDIFF(SECOND, NOW(), e.end_at) AS secs_to_end, "
            "b.submitted_at AS voted_at "
            "FROM elections e "
            "LEFT JOIN ballots b "
            "ON b.election_id = e.id AND b.student_id = %s "
            f"WHERE e.department_id = %s "
            "AND e.school_year_id = %s "
            f"AND e.status IN ({marks}) "
            "ORDER BY e.start_at DESC, e.id DESC",
            (
                student["id"],
                student["department_id"],
                student["school_year_id"],
            ) + VISIBLE_STATUSES
        )

    priority = {
        "open": 0,
        "not_started": 1,
        "upcoming": 2,
        "ended": 3,
        "voted": 4,
        "closed": 5,
        "published": 6,
    }

    for row in rows:
        row["state"] = voting_state(
            row, row["voted_at"] is not None
        )
        if student.get("kind") == "admin":
            # Keep election visibility, but do not offer voting until the schema supports it.
            row["state_label"] = "Super Admin voting unavailable"
            row["tone"] = "slate"
            row["can_vote"] = False

        else:
            row["state_label"], row["tone"] = STATE_LABELS[row["state"]]
            row["can_vote"] = row["state"] == "open"
            # shown even to students who voted
            row["results_published"] = row["status"] == "published"

    rows.sort(key=lambda r: priority[r["state"]])
    return rows


# ================================================================ the ballot

def ballot_positions(election_id):
    """Positions of the election, each with its APPROVED candidates only (the ballot)."""
    positions = fetch_all(
        "SELECT ep.position_id, p.name, p.description FROM election_positions ep "
        "JOIN positions p ON p.id = ep.position_id WHERE ep.election_id = %s AND ep.is_active = 1 "
        "ORDER BY ep.display_order, p.display_order, p.name", (election_id,))
    candidates = fetch_all(
        "SELECT c.id, c.position_id, c.platform, c.photo_path, s.first_name, s.middle_name, s.last_name, s.year_level, s.section "
        "FROM candidates c JOIN students s ON s.id = c.student_id "
        "WHERE c.election_id = %s AND c.status = 'approved' ORDER BY s.last_name, s.first_name", (election_id,))
    by_position = {}
    for c in candidates:
        c["full_name"] = " ".join(part for part in (
            c["first_name"], c["middle_name"], c["last_name"]) if part)
        by_position.setdefault(c["position_id"], []).append(c)
    for p in positions:
        p["candidates"] = by_position.get(p["position_id"], [])
    return positions


def parse_selections(form, positions):
    """Turn the submitted form into {position_id: candidate_id}. Returns (selections, errors).

    A blank choice means 'no vote for this position'. Anything that is not a candidate that is on THIS
    ballot, or a position that is not on it, is rejected: the browser can send anything.
    """
    errors, selections = [], {}
    valid = {p["position_id"]: {c["id"]
                                for c in p["candidates"]} for p in positions}
    for key in form.keys():
        if key.startswith("position_") and (not key[9:].isdigit() or int(key[9:]) not in valid):
            errors.append(
                "The ballot contains a position that is not part of this election.")
            break
    for p in positions:
        raw = (form.get(f"position_{p['position_id']}") or "").strip()
        if not raw:
            continue
        if not raw.isdigit() or int(raw) not in valid[p["position_id"]]:
            errors.append(
                f"Invalid choice for {p['name']}. Please choose a candidate from the list.")
        else:
            selections[p["position_id"]] = int(raw)
    if not errors and not selections:
        errors.append(
            "Please choose at least one candidate before continuing.")
    return selections, errors


def review_lines(positions, selections):
    """What the student is about to submit, for the review page."""
    lines = []
    for p in positions:
        chosen = next((c for c in p["candidates"] if c["id"]
                      == selections.get(p["position_id"])), None)
        lines.append({"position": p["name"], "candidate": chosen["full_name"] if chosen else None,
                      "position_id": p["position_id"], "candidate_id": chosen["id"] if chosen else None})
    return lines


# ================================================================ casting the vote

def cast_ballot(user, election_id, form):
    """Validate everything again and write the ballot. Returns (ok, error_message).

    Nothing from the review page is trusted: the whole ballot is checked again here.
    """
    student = get_voter(user)
    if student is None:
        return False, "No student record is linked to your account."
    if student.get("kind") == "admin":
        return False, (
            "Super Admin voting is temporarily unavailable because the current "
            "database schema supports student ballots only."
        )
    election = get_election(election_id)
    problem = access_problem(election, student)
    if problem == "missing":
        return False, "This election does not exist."
    if problem:
        return False, problem[1]
    if voting_state(election, False) != "open":
        return False, "Voting is not open for this election."
    if my_ballot(election_id, student):
        return False, "You have already voted in this election. A ballot cannot be changed."

    positions = ballot_positions(election_id)
    selections, errors = parse_selections(form, positions)
    if errors:
        return False, errors[0]

    db = get_db()
    db.rollback()                       # end the read-only transaction, start clean
    db.start_transaction()
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO ballots (election_id, student_id) VALUES (%s, %s)",
            (election_id, student["id"])
        )
        ballot_id = cursor.lastrowid
        for position_id, candidate_id in selections.items():
            cursor.execute("INSERT INTO votes (ballot_id, election_id, position_id, candidate_id) VALUES (%s, %s, %s, %s)",
                           (ballot_id, election_id, position_id, candidate_id))
        # The audit entry says THAT this person voted, never what, and never the ballot id.
        log_action(user["id"], "ballot_cast", "voting", f"Cast a ballot in '{election['name']}'",
                   affected_record=f"election:{election_id}", commit=False)
        db.commit()
        return True, None
    except mysql.connector.Error as error:
        # all or nothing: no ballot without its votes, no votes without a ballot
        db.rollback()
        if getattr(error, "errno", None) == DUPLICATE_KEY:
            return False, "You have already voted in this election. A ballot cannot be changed."
        # one of the database triggers refused it
        if getattr(error, "sqlstate", None) == "45000":
            return False, (error.msg.split(": ", 1)[-1] if error.msg else "The database refused this ballot.")
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
