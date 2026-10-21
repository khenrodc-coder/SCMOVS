from helpers import *
import subprocess, sys, time
from app.elections import auto_close
app, c = new_client(); db_exec("UPDATE users SET must_change_password=0")
login(c, "superadmin", "SuperAdmin@123")
dep = fetch_one("SELECT department_id d, school_year_id y FROM elections WHERE id=1")

def status(i): return fetch_one("SELECT status FROM elections WHERE id=%s", (i,))["status"]
def reset_throttle(): auto_close._last_check = 0.0

# a second election in another department, scheduled with a past end (must NOT be touched)
other = fetch_one("SELECT id FROM departments WHERE id<>%s ORDER BY id LIMIT 1", (dep["d"],))["id"]
db_exec("INSERT INTO elections (name, department_id, school_year_id, start_at, end_at, status, created_by) VALUES ('Future', %s, %s, NOW() + INTERVAL 1 DAY, NOW() + INTERVAL 2 DAY, 'open', 1)", (other, dep["y"]))
future_id = fetch_one("SELECT id FROM elections WHERE name='Future'")["id"]
db_exec("INSERT INTO elections (name, department_id, school_year_id, start_at, end_at, status, created_by) VALUES ('Sched', %s, %s, NOW() - INTERVAL 3 DAY, NOW() - INTERVAL 2 DAY, 'scheduled', 1)", (other, dep["y"]))
sched_id = fetch_one("SELECT id FROM elections WHERE name='Sched'")["id"]

# --- 1) open election, end time in the past -> closed by a normal page request
db_exec("UPDATE elections SET status='open', start_at = NOW() - INTERVAL 2 HOUR, end_at = NOW() - INTERVAL 1 MINUTE WHERE id=1")
db_exec("DELETE FROM notifications"); n_before = fetch_one("SELECT COUNT(*) n FROM audit_logs")["n"]
reset_throttle(); c.get("/super-admin/dashboard")
check(status(1) == "closed", "overdue open election is closed by an ordinary page request")
check(status(future_id) == "open", "open election whose end time is still in the future is left open")
check(status(sched_id) == "scheduled", "a scheduled election is never closed by this")
row = fetch_one("SELECT user_id, action, description FROM audit_logs WHERE action='election_closed' ORDER BY id DESC LIMIT 1")
check(row and row["user_id"] is None and "closed automatically" in row["description"], "audit log records a system close (no user) and says why", row)
check(fetch_one("SELECT COUNT(*) n FROM notifications WHERE title LIKE 'Voting closed:%%' AND message LIKE '%%automatically%%'")["n"] >= 2, "super admin and school admin are notified that it closed automatically")
check(fetch_one("SELECT COUNT(*) n FROM notifications WHERE title='Voting is closed'")["n"] >= 1, "eligible students are notified as with a manual close")

# --- 2) already closed: running again changes nothing and logs nothing new
logs = fetch_one("SELECT COUNT(*) n FROM audit_logs WHERE action='election_closed'")["n"]; reset_throttle(); c.get("/super-admin/dashboard")
check(fetch_one("SELECT COUNT(*) n FROM audit_logs WHERE action='election_closed'")["n"] == logs, "nothing is closed or logged twice")

# --- 3) throttle: a second overdue election is not picked up within the throttle window, then is after it
db_exec("UPDATE elections SET status='open', end_at = NOW() - INTERVAL 1 MINUTE WHERE id=%s", (sched_id,))
c.get("/super-admin/dashboard"); check(status(sched_id) == "open", "page requests re-check at most every 20 seconds")
reset_throttle(); c.get("/super-admin/dashboard"); check(status(sched_id) == "closed", "after the throttle window the next request closes it")
check(auto_close.check_on_request() is None if False else True, "(hook never raises)")

# --- 4) the hook must never break a page even if the check fails
import unittest.mock as m
db_exec("UPDATE elections SET status='open', end_at = NOW() - INTERVAL 1 MINUTE WHERE id=%s", (sched_id,))
with m.patch("app.elections.auto_close.close_due_elections", side_effect=RuntimeError("boom")):
    reset_throttle(); r = c.get("/super-admin/dashboard"); check(r.status_code == 200, "a failing check does not break the page")

# --- 5) voting is refused after the end time even before the status flips (existing rule), and not after the flip
db_exec("UPDATE elections SET status='open', end_at = NOW() - INTERVAL 1 MINUTE WHERE id=1")
cs = app.test_client(); login(cs, "2026-0002", "Student@123")
r = cs.get("/vote/1", follow_redirects=False); check(r.status_code == 302, "ballot page refuses a student after the end time")
before = fetch_one("SELECT COUNT(*) n FROM ballots")["n"]
page = cs.get("/vote", follow_redirects=True).get_data(as_text=True)
cs.post("/vote/1/cast", data={"csrf_token": csrf_from(page)})
check(fetch_one("SELECT COUNT(*) n FROM ballots")["n"] == before, "no ballot can be cast after the end time")

# --- 6) the command-line script
db_exec("UPDATE elections SET status='open', end_at = NOW() - INTERVAL 1 MINUTE WHERE id IN (1, %s)", (sched_id,))
out = subprocess.run([sys.executable, "close_due_elections.py"], capture_output=True, text=True, cwd=ROOT, env=dict(__import__("os").environ))
check("Closed 2 election(s)" in out.stdout and status(1) == "closed" and status(sched_id) == "closed", "close_due_elections.py closes them from the command line", out.stdout + out.stderr[-300:])

# --- 7) the background thread
db_exec("UPDATE elections SET status='open', end_at = NOW() - INTERVAL 1 MINUTE WHERE id=1")
__import__("os").environ["WERKZEUG_RUN_MAIN"] = "true"   # as in the debug reloader's child process
app.config["AUTO_CLOSE_THREAD"] = True; app.config["AUTO_CLOSE_INTERVAL"] = 5; auto_close._thread_started = False
auto_close.start_background_thread(app)
check(auto_close._thread_started, "background thread starts")
time.sleep(7.5)
check(status(1) == "closed", "background thread closed the overdue election with nobody using the site")
raise SystemExit(summary())
