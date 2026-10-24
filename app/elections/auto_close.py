"""Open elections when their scheduled start time arrives, and close them when their end time passes.

Three safety nets, all using the SAME code path as the manual "Open voting" / "Close voting" buttons
(app.elections.services.change_status), so every rule, notification and audit entry works exactly the same:

  1. A background thread (long-running servers: python run.py, gunicorn). It checks right after the app starts (to catch up on
     anything that was due while the app was off), then sleeps until the very next start or end time, so elections open
     and close within about a second of the set time. It also re-checks every AUTO_CLOSE_INTERVAL seconds (default 5) and
     wakes up at once when an election is scheduled or its dates are edited.
  2. Every page request also checks (at most once every 2 seconds per process). This is what keeps it working on
     hosts that do not allow background threads (for example Vercel).
  3. `python close_due_elections.py` can be run from Windows Task Scheduler or a cron job.

Opening: only elections that were SCHEDULED (never drafts) whose start time has arrived and whose end time has not.
They must pass the same checks as the manual Open button (positions, an approved candidate for every position, an active
school year, no overlapping election). If a check fails, the Super Admins and School Admins get ONE notice with the
reason, and the system keeps retrying: fix the problem and the election opens by itself.
Closing: only elections that are 'open' and whose end time has passed. Voting was already refused after the end time;
this only brings the status up to date. If two processes try at once, the database lets only one win.
"""
import logging
import os
import threading
import time

from app.db import fetch_all, fetch_one

log = logging.getLogger(__name__)

_lock = threading.Lock()
_last_check = 0.0
_thread_started = False
_wake = threading.Event()
REQUEST_THROTTLE_SECONDS = 2


def open_due_elections():
    """Open every scheduled election whose start time has arrived. Returns how many were opened."""
    from app.elections import services

    opened = 0
    due = fetch_all("SELECT id FROM elections WHERE status = 'scheduled' AND start_at <= NOW()")
    for row in due:
        election = services.get_election(row["id"])
        if election is None or election["status"] != "scheduled":
            continue                                       # someone else already handled it
        if election["end_at"] <= services.db_now():
            services.report_open_problem(election, "Its voting period ended before it could be opened. "
                                                   "Edit the dates to give it a new voting period.")
            continue
        error = services.change_status(election, "open", None, automatic=True)
        if error is None:
            opened += 1
        elif "changed by someone else" not in error:
            services.report_open_problem(election, error)   # tells the admins once; retried on the next check
    return opened


def close_due_elections():
    """Close every open election whose end time has passed. Returns how many were closed."""
    from app.elections import services

    due = fetch_all("SELECT id FROM elections WHERE status = 'open' AND end_at <= NOW()")
    closed = 0
    for row in due:
        election = services.get_election(row["id"])
        if election is None or election["status"] != "open":
            continue
        error = services.change_status(election, "close", None, automatic=True)
        if error is None:
            closed += 1
        else:
            log.info("Election %s was not auto-closed: %s", row["id"], error)
    return closed


def update_election_statuses():
    """Open what is due, then close what is over. Returns (opened, closed)."""
    return open_due_elections(), close_due_elections()


def wake():
    """Ask the background thread to re-check now (called when an election is scheduled or edited)."""
    _wake.set()


def seconds_to_next_event():
    """Seconds until the next scheduled start or open election end, or None when nothing is coming up."""
    row = fetch_one(
        "SELECT MIN(secs) AS secs FROM ("
        " SELECT TIMESTAMPDIFF(SECOND, NOW(), start_at) AS secs FROM elections WHERE status = 'scheduled' AND start_at > NOW()"
        " UNION ALL"
        " SELECT TIMESTAMPDIFF(SECOND, NOW(), end_at) FROM elections WHERE status = 'open' AND end_at > NOW()) t")
    return None if row is None or row["secs"] is None else int(row["secs"])


def check_on_request():
    """before_request hook: cheap, throttled, and never allowed to break a page."""
    from flask import request
    global _last_check
    if request.endpoint in (None, "static") or request.path.startswith(("/static/", "/media/")):
        return None
    now = time.monotonic()
    with _lock:
        if now - _last_check < REQUEST_THROTTLE_SECONDS:
            return None
        _last_check = now
    try:
        update_election_statuses()
    except Exception:                                    # noqa: BLE001 - a failed check must not break the page
        log.exception("Automatic election status check failed")
    return None


def start_background_thread(app):
    """Start the periodic checker once per process (not in tests, not on serverless hosts)."""
    global _thread_started
    if _thread_started or not app.config.get("AUTO_CLOSE_THREAD", True):
        return
    if os.environ.get("VERCEL") == "1":
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return                                            # the Flask debug reloader starts the app twice
    _thread_started = True
    interval = max(2, int(app.config.get("AUTO_CLOSE_INTERVAL", 5)))
    base_url = app.config.get("PUBLIC_BASE_URL") or "http://127.0.0.1:5000"

    def loop():
        delay = 1.5                                       # first pass right after start-up: catch up on anything overdue
        while True:
            _wake.wait(timeout=delay)
            _wake.clear()
            delay = interval
            try:
                # a request context lets url_for() build the notification links, as in a normal click
                with app.test_request_context("/", base_url=base_url):
                    update_election_statuses()
                    secs = seconds_to_next_event()
                if secs is not None:                      # sleep until the next start/end moment (never longer than `interval`)
                    delay = max(0.4, min(interval, secs + 0.5))
            except Exception:                             # noqa: BLE001
                log.exception("Background election status check failed")

    threading.Thread(target=loop, name="scmovs-auto-close", daemon=True).start()
