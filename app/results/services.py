"""Election results (Phase 7B): calculate -> verify -> publish.

HOW RESULTS ARE KEPT HONEST
  * Counted from the `votes` table only. This module never joins `votes` to `ballots`, so a result can
    never reveal who voted for whom. (Counting ballots and counting votes are two separate queries.)
  * Calculating takes a SNAPSHOT (election_results + election_result_runs) with a SHA-256 checksum. What an
    administrator verifies and publishes is that snapshot, not a live count that could still change.
  * Before verifying and before publishing, the snapshot is checked twice: against its checksum, and against
    a fresh recount of the votes. If anything differs, the action is refused and the results must be recalculated.
  * Separation of duties: the administrator who calculated the results cannot verify them
    (Settings -> Election -> "Results need a second administrator"). So nobody can calculate and publish alone.
  * Every step is one transaction that first locks the election row. The database triggers
    (trg_election_results_*, trg_elections_bu) refuse the same mistakes if this code ever slipped.

COUNTING RULES (plurality, no minimum turnout)
  * Each position has `seats` seats. The candidates with the most votes win, but only candidates with at
    least one vote can win.
  * A tie that reaches across the last seat is NOT decided automatically: those candidates are marked
    'tie' and the administrator must acknowledge it before verifying. The school decides how to resolve it.
  * Only APPROVED candidates are counted. Votes for a candidate who was disqualified after voting are
    listed as "excluded votes" so nothing disappears silently.
"""
import hashlib

import mysql.connector
from flask import url_for

from app.audit.services import log_action
from app.auth.services import has_permission
from app.db import fetch_all, fetch_one, get_db
from app.elections import services as elections
from app.settings.services import get_bool
from app.utils import escape_like, get_page
from app.voting import services as voting

PER_PAGE = 10
ADMIN_STATUSES = ("closed", "pending_verification", "verified", "published")
OUTCOME_LABELS = {"winner": "Winner",
                  "tie": "Tie", "not_elected": "Not elected"}
STEPS = (("closed", "Voting closed"), ("pending_verification", "Calculated"), ("verified", "Verified"),
         ("published", "Published"))


# ================================================================ counting (pure rules, easy to test)

def rank_position(candidates, seats):
    """Give every candidate a 'rank' and an 'outcome'. Candidates are dicts with 'name' and 'votes'.

    Returns the list sorted by votes (highest first, then name). Ranks share a number when votes are equal.
    """
    ordered = sorted(
        candidates, key=lambda c: (-c["votes"], c["name"].lower()))
    rank, previous = 0, None
    for position, candidate in enumerate(ordered, start=1):
        if candidate["votes"] != previous:
            rank, previous = position, candidate["votes"]
        candidate["rank"] = rank
        candidate["outcome"] = "not_elected"

    # nobody wins a seat with zero votes
    contenders = [c for c in ordered if c["votes"] > 0]
    if len(contenders) <= seats:
        for candidate in contenders:
            candidate["outcome"] = "winner"
    else:
        # votes of the last seat holder
        cutoff = contenders[seats - 1]["votes"]
        # the next candidate is level: a tie over the last seat
        if contenders[seats]["votes"] == cutoff:
            for candidate in contenders:
                if candidate["votes"] > cutoff:
                    candidate["outcome"] = "winner"
                elif candidate["votes"] == cutoff:
                    candidate["outcome"] = "tie"
        else:
            for candidate in contenders[:seats]:
                candidate["outcome"] = "winner"
    return ordered


def _full_name(row):
    return " ".join(part for part in (row["first_name"], row["middle_name"], row["last_name"]) if part)


def tally(election_id):
    """Live count from the votes table: a list of positions, each with ranked candidates."""
    positions = fetch_all(
        "SELECT ep.position_id, p.name, p.seats FROM election_positions ep JOIN positions p ON p.id = ep.position_id "
        "WHERE ep.election_id = %s AND ep.is_active = 1 ORDER BY ep.display_order, p.display_order, p.name",
        (election_id,))
    rows = fetch_all(
        "SELECT c.id AS candidate_id, c.position_id, s.first_name, s.middle_name, s.last_name, COUNT(v.id) AS votes "
        "FROM candidates c JOIN students s ON s.id = c.student_id LEFT JOIN votes v ON v.candidate_id = c.id "
        "WHERE c.election_id = %s AND c.status = 'approved' "
        "GROUP BY c.id, c.position_id, s.first_name, s.middle_name, s.last_name", (election_id,))
    by_position = {}
    for row in rows:
        by_position.setdefault(row["position_id"], []).append(
            {"candidate_id": row["candidate_id"], "name": _full_name(row), "votes": int(row["votes"])})
    for position in positions:
        position["candidates"] = rank_position(by_position.get(
            position["position_id"], []), int(position["seats"]))
    return positions


def flatten(positions):
    """The rows that make up a result, in a fixed order (used for the checksum and for comparisons)."""
    return sorted((p["position_id"], c["candidate_id"], c["votes"], c["rank"], c["outcome"])
                  for p in positions for c in p["candidates"])


def checksum(election_id, ballots_counted, flat_rows):
    text = f"{election_id}|{ballots_counted}|" + \
        ";".join(":".join(str(x) for x in row) for row in flat_rows)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _count_ballots(election_id):
    """How many ballots were cast. A plain count: never joined to votes."""
    return fetch_one("SELECT COUNT(*) AS n FROM ballots WHERE election_id = %s", (election_id,))["n"]


def _eligible_voters(election_id):
    row = fetch_one(
        "SELECT eligible_voters FROM v_election_participation WHERE election_id = %s", (election_id,))
    return int(row["eligible_voters"]) if row else 0


def _excluded_votes(election_id):
    """Votes for candidates that are not approved any more (counted, but never part of the results)."""
    return fetch_one("SELECT COUNT(*) AS n FROM votes v JOIN candidates c ON c.id = v.candidate_id "
                     "WHERE v.election_id = %s AND c.status <> 'approved'", (election_id,))["n"]


# ================================================================ reading the snapshot

def get_election(election_id):
    """The election with its result run and who calculated / verified / published it."""
    return fetch_one(
        "SELECT e.id, e.name, e.status, e.department_id, e.school_year_id, e.verified_at, e.published_at, "
        "e.verified_by, e.published_by, d.name AS department, sy.name AS school_year, "
        "r.calculated_by, r.calculated_at, r.eligible_voters, r.ballots_counted, r.excluded_votes, r.checksum, "
        "cu.full_name AS calculated_by_name, vu.full_name AS verified_by_name, pu.full_name AS published_by_name "
        "FROM elections e JOIN departments d ON d.id = e.department_id JOIN school_years sy ON sy.id = e.school_year_id "
        "LEFT JOIN election_result_runs r ON r.election_id = e.id LEFT JOIN users cu ON cu.id = r.calculated_by "
        "LEFT JOIN users vu ON vu.id = e.verified_by LEFT JOIN users pu ON pu.id = e.published_by "
        "WHERE e.id = %s", (election_id,))


def snapshot_rows(election_id):
    return fetch_all("SELECT position_id, candidate_id, vote_count, rank_no, outcome FROM election_results "
                     "WHERE election_id = %s ORDER BY position_id, candidate_id", (election_id,))


def stored_flat(election_id):
    return sorted((r["position_id"], r["candidate_id"], int(r["vote_count"]), int(r["rank_no"]), r["outcome"])
                  for r in snapshot_rows(election_id))


def load_results(election_id, ballots_counted):
    """The saved results as positions with candidates, vote shares and abstentions, for display.

    Every active position of the election is listed, even one whose candidates were all excluded.
    """
    positions = fetch_all(
        "SELECT ep.position_id, p.name, p.seats FROM election_positions ep JOIN positions p ON p.id = ep.position_id "
        "WHERE ep.election_id = %s AND ep.is_active = 1 ORDER BY ep.display_order, p.display_order, p.name", (election_id,))
    index = {p["position_id"]: p for p in positions}
    for position in positions:
        position["candidates"] = []
    rows = fetch_all(
        "SELECT r.position_id, r.candidate_id, s.first_name, s.middle_name, s.last_name, r.vote_count, r.rank_no, r.outcome "
        "FROM election_results r JOIN candidates c ON c.id = r.candidate_id JOIN students s ON s.id = c.student_id "
        "WHERE r.election_id = %s ORDER BY r.rank_no, s.last_name, s.first_name", (election_id,))
    for row in rows:
        if row["position_id"] in index:
            index[row["position_id"]]["candidates"].append(
                {"candidate_id": row["candidate_id"], "name": _full_name(row), "votes": int(row["vote_count"]),
                 "rank": int(row["rank_no"]), "outcome": row["outcome"]})
    for position in positions:
        total = sum(c["votes"] for c in position["candidates"])
        position["total_votes"] = total
        position["abstained"] = max(int(ballots_counted or 0) - total, 0)
        position["has_tie"] = any(
            c["outcome"] == "tie" for c in position["candidates"])
        for c in position["candidates"]:
            c["percent"] = round(100 * c["votes"] / total, 1) if total else 0
    return positions


def chart_data(positions):
    return [{"id": p["position_id"], "name": p["name"], "labels": [c["name"] for c in p["candidates"]],
             "votes": [c["votes"] for c in p["candidates"]], "outcomes": [c["outcome"] for c in p["candidates"]]}
            for p in positions]


def integrity_problem(election_id, run):
    """None when the saved results still match their checksum AND a fresh recount of the votes."""
    stored = stored_flat(election_id)
    if checksum(election_id, run["ballots_counted"], stored) != run["checksum"]:
        return "The saved results no longer match their checksum. Send them back and recalculate."
    live = tally(election_id)
    if flatten(live) != stored or _count_ballots(election_id) != run["ballots_counted"]:
        return ("The votes or the candidates changed after the results were calculated (for example a candidate "
                "was disqualified). Send the results back and recalculate.")
    return None


# ================================================================ admin: who may do what, and why not

def action_states(user, election):
    """For each action: (allowed, reason shown next to a disabled button)."""
    status = election["status"]
    calculator = election["calculated_by"]
    states = {}
    if not has_permission("elections.manage"):
        states["calculate"] = (
            False, "You do not have permission to calculate results.")
    elif status not in ("closed", "pending_verification"):
        states["calculate"] = (
            False, "Results can only be calculated while the election is closed and not yet verified.")
    else:
        states["calculate"] = (True, None)

    if not has_permission("results.verify"):
        states["verify"] = (
            False, "You do not have permission to verify results.")
    elif status != "pending_verification":
        states["verify"] = (
            False, "Only calculated results that are waiting for verification can be verified.")
    elif get_bool("election_separate_verifier", True) and calculator == user["id"]:
        states["verify"] = (
            False, "You calculated these results, so a different administrator must verify them.")
    else:
        states["verify"] = (True, None)

    if not has_permission("results.verify"):
        states["return"] = (
            False, "You do not have permission to send results back.")
    elif status not in ("pending_verification", "verified"):
        states["return"] = (
            False, "Only calculated or verified results can be sent back.")
    else:
        states["return"] = (True, None)

    if not has_permission("elections.publish"):
        states["publish"] = (
            False, "You do not have permission to publish results.")
    elif status != "verified":
        states["publish"] = (
            False, "Results must be verified before they can be published.")
    else:
        states["publish"] = (True, None)
    return states


def list_for_admin(args):
    q = args.get("q", "").strip()[:100]
    status = args.get("status", "")
    statuses = (status,) if status in ADMIN_STATUSES else ADMIN_STATUSES
    where, params = [
        "e.status IN (" + ", ".join(["%s"] * len(statuses)) + ")"], list(statuses)
    if q:
        where.append("e.name LIKE %s")
        params.append("%" + escape_like(q) + "%")
    where_sql = " AND ".join(where)
    total = fetch_one(
        f"SELECT COUNT(*) AS n FROM elections e WHERE {where_sql}", tuple(params))["n"]
    page, pages = get_page(args, total, PER_PAGE)
    items = fetch_all(
        "SELECT e.id, e.name, e.status, e.end_at, d.name AS department, sy.name AS school_year, r.calculated_at, "
        "r.ballots_counted, r.eligible_voters, cu.full_name AS calculated_by_name, e.verified_at, e.published_at "
        "FROM elections e JOIN departments d ON d.id = e.department_id JOIN school_years sy ON sy.id = e.school_year_id "
        "LEFT JOIN election_result_runs r ON r.election_id = e.id LEFT JOIN users cu ON cu.id = r.calculated_by "
        f"WHERE {where_sql} ORDER BY e.end_at DESC, e.id DESC LIMIT %s OFFSET %s",
        tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE))
    return {"items": items, "page": page, "pages": pages, "total": total, "q": q, "status": status,
            "filters": {k: v for k, v in (("q", q), ("status", status)) if v}}


# ================================================================ admin actions (one locked transaction each)

def _begin():
    db = get_db()
    db.rollback()
    db.start_transaction(isolation_level="READ COMMITTED")
    return db, db.cursor(dictionary=True)


def _lock(cursor, election_id):
    cursor.execute("SELECT id, name, status, department_id, school_year_id FROM elections WHERE id = %s FOR UPDATE",
                   (election_id,))
    return cursor.fetchone()


def _database_refusal(error):
    """A trigger said no: show its plain message. Anything else is a real error."""
    if getattr(error, "sqlstate", None) == "45000":
        return error.msg.split(": ", 1)[-1] if error.msg else "The database refused this change."
    return None


def calculate(election_id, actor):
    """Count the votes and save the snapshot. Returns an error message or None."""
    db, cursor = _begin()
    try:
        election = _lock(cursor, election_id)
        if election is None or election["status"] not in ("closed", "pending_verification"):
            db.rollback()
            return "Results can only be calculated while the election is closed and not yet verified."
        positions = tally(election_id)
        if not positions:
            db.rollback()
            return "This election has no positions, so there is nothing to count."
        flat = flatten(positions)
        ballots, eligible, excluded = _count_ballots(election_id), _eligible_voters(
            election_id), _excluded_votes(election_id)

        # a recalculation replaces the old one
        cursor.execute(
            "DELETE FROM election_results WHERE election_id = %s", (election_id,))
        cursor.execute(
            "DELETE FROM election_result_runs WHERE election_id = %s", (election_id,))
        cursor.execute("INSERT INTO election_result_runs (election_id, calculated_by, eligible_voters, ballots_counted, "
                       "excluded_votes, checksum) VALUES (%s, %s, %s, %s, %s, %s)",
                       (election_id, actor["id"], eligible, ballots, excluded, checksum(election_id, ballots, flat)))
        for position_id, candidate_id, votes, rank, outcome in flat:
            cursor.execute("INSERT INTO election_results (election_id, position_id, candidate_id, vote_count, rank_no, outcome) "
                           "VALUES (%s, %s, %s, %s, %s, %s)", (election_id, position_id, candidate_id, votes, rank, outcome))
        cursor.execute("UPDATE elections SET status = 'pending_verification', verified_by = NULL, verified_at = NULL "
                       "WHERE id = %s", (election_id,))
        ties = sum(1 for p in positions if any(
            c["outcome"] == "tie" for c in p["candidates"]))
        log_action(actor["id"], "results_calculated", "results",
                   f"Calculated results of '{election['name']}': {ballots} ballots, {len(positions)} positions"
                   + (f", {ties} tie(s)" if ties else "") +
                   (f", {excluded} excluded vote(s)" if excluded else ""),
                   affected_record=f"election:{election_id}", commit=False)
        db.commit()
        return None
    except mysql.connector.Error as error:
        db.rollback()
        message = _database_refusal(error)
        if message:
            return message
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def verify(election_id, actor, remarks, acknowledged_ties):
    """An administrator confirms the calculated results. Returns an error message or None."""
    remarks = (remarks or "").strip()
    if len(remarks) > 500:
        return "Remarks must be 500 characters or fewer."
    db, cursor = _begin()
    try:
        election = _lock(cursor, election_id)
        if election is None or election["status"] != "pending_verification":
            db.rollback()
            return "Only calculated results that are waiting for verification can be verified."
        run = fetch_one("SELECT calculated_by, ballots_counted, checksum FROM election_result_runs WHERE election_id = %s",
                        (election_id,))
        if run is None:
            db.rollback()
            return "These results have not been calculated yet."
        same_person = run["calculated_by"] == actor["id"]
        if same_person and get_bool("election_separate_verifier", True):
            db.rollback()
            return "You calculated these results, so a different administrator must verify them."
        problem = integrity_problem(election_id, run)
        if problem:
            db.rollback()
            return problem
        has_tie = any(row[4] == "tie" for row in stored_flat(election_id))
        if has_tie and not acknowledged_ties:
            db.rollback()
            return ("There is a tie for a seat. Tick the box to confirm you know it will be published as a tie "
                    "(it is not decided automatically).")
        cursor.execute("UPDATE elections SET status = 'verified', verified_by = %s, verified_at = NOW() WHERE id = %s",
                       (actor["id"], election_id))
        log_action(actor["id"], "results_verified", "results",
                   f"Verified results of '{election['name']}'" +
                   (" (tie acknowledged)" if has_tie else "")
                   + (" (same administrator calculated them: allowed by settings)" if same_person else "")
                   + (f". Remarks: {remarks}" if remarks else ""), affected_record=f"election:{election_id}", commit=False)
        db.commit()
        return None
    except mysql.connector.Error as error:
        db.rollback()
        message = _database_refusal(error)
        if message:
            return message
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def send_back(election_id, actor, reason):
    """Throw the calculated results away (the election returns to 'closed'). Returns an error message or None."""
    reason = (reason or "").strip()
    if not 10 <= len(reason) <= 500:
        return "Please explain why the results are sent back (10 to 500 characters)."
    db, cursor = _begin()
    try:
        election = _lock(cursor, election_id)
        if election is None or election["status"] not in ("pending_verification", "verified"):
            db.rollback()
            return "Only calculated or verified results can be sent back."
        run = fetch_one(
            "SELECT calculated_by FROM election_result_runs WHERE election_id = %s", (election_id,))
        # Step by step so the database triggers allow it: verified -> pending -> (delete) -> closed
        cursor.execute("UPDATE elections SET status = 'pending_verification', verified_by = NULL, verified_at = NULL "
                       "WHERE id = %s", (election_id,))
        cursor.execute(
            "DELETE FROM election_results WHERE election_id = %s", (election_id,))
        cursor.execute(
            "DELETE FROM election_result_runs WHERE election_id = %s", (election_id,))
        cursor.execute(
            "UPDATE elections SET status = 'closed' WHERE id = %s", (election_id,))
        if run and run["calculated_by"] != actor["id"]:
            cursor.execute("INSERT INTO notifications (user_id, title, message, related_module, link_url) "
                           "VALUES (%s, %s, %s, 'results', %s)",
                           (run["calculated_by"], "Results sent back",
                            f"The results of '{election['name']}' were sent back for recalculation. Reason: {reason}"[
                                :500],
                            url_for("results.admin_detail", election_id=election_id)))
        log_action(actor["id"], "results_returned", "results",
                   f"Sent back results of '{election['name']}' for recalculation. Reason: {reason}"[
                       :500],
                   affected_record=f"election:{election_id}", commit=False)
        db.commit()
        return None
    except mysql.connector.Error as error:
        db.rollback()
        message = _database_refusal(error)
        if message:
            return message
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def publish(election_id, actor):
    """Make verified results official and tell the eligible students. Returns an error message or None."""
    db, cursor = _begin()
    try:
        election = _lock(cursor, election_id)
        if election is None or election["status"] != "verified":
            db.rollback()
            return "Results must be verified before they can be published."
        run = fetch_one("SELECT calculated_by, ballots_counted, checksum FROM election_result_runs WHERE election_id = %s",
                        (election_id,))
        if run is None:
            db.rollback()
            return "These results have not been calculated yet."
        # one more look right before they become official
        problem = integrity_problem(election_id, run)
        if problem:
            db.rollback()
            return problem
        cursor.execute("UPDATE elections SET status = 'published', published_by = %s, published_at = NOW() WHERE id = %s",
                       (actor["id"], election_id))
        elections.notify_eligible_students(
            cursor, election, "Results published", f"The official results of '{election['name']}' have been published.",
            url_for("results.view", election_id=election_id))
        log_action(actor["id"], "results_published", "results", f"Published results of '{election['name']}'",
                   affected_record=f"election:{election_id}", commit=False)
        db.commit()
        return None
    except mysql.connector.Error as error:
        db.rollback()
        message = _database_refusal(error)
        if message:
            return message
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


# ================================================================ who may read PUBLISHED results

def _published_scope(user):
    """('all', None) | ('department', id) | ('none', None). Students see their own department only."""
    if user["role"] in ("super_admin", "school_admin"):
        return "all", None
    student = voting.get_student(user["id"])
    if student:
        return "department", student["department_id"]
    return ("all", None) if user["role"] == "council_officer" else ("none", None)


def published_list(user):
    scope, department_id = _published_scope(user)
    if scope == "none":
        return []
    sql = ("SELECT e.id, e.name, e.published_at, d.name AS department, sy.name AS school_year, "
           "r.ballots_counted, r.eligible_voters FROM elections e JOIN departments d ON d.id = e.department_id "
           "JOIN school_years sy ON sy.id = e.school_year_id JOIN election_result_runs r ON r.election_id = e.id "
           "WHERE e.published_at IS NOT NULL AND e.status IN ('published', 'archived')")
    params = ()
    if scope == "department":
        sql += " AND e.department_id = %s"
        params = (department_id,)
    return fetch_all(sql + " ORDER BY e.published_at DESC, e.id DESC", params)


def get_published(election_id, user):
    """(election, problem). problem is None, 'missing' (404) or a message (403)."""
    election = get_election(election_id)
    if election is None or election["published_at"] is None or election["status"] not in ("published", "archived"):
        # unpublished results do not exist as far as students can tell
        return None, "missing"
    scope, department_id = _published_scope(user)
    if scope == "none" or (scope == "department" and election["department_id"] != department_id):
        return None, "These results are not available to you."
    return election, None
