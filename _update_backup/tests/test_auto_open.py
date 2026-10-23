from helpers import *
import subprocess, sys, time, os
from app.elections import auto_close
os.environ["WERKZEUG_RUN_MAIN"] = "true"
app, c = new_client(); db_exec("UPDATE users SET must_change_password=0")
login(c, "superadmin", "SuperAdmin@123")
e1 = fetch_one("SELECT department_id d, school_year_id y FROM elections WHERE id=1")
other = fetch_one("SELECT id FROM departments WHERE id<>%s ORDER BY id LIMIT 1", (e1["d"],))["id"]
def status(i): return fetch_one("SELECT status FROM elections WHERE id=%s", (i,))["status"]
def tick(): auto_close._last_check = 0.0; c.get("/super-admin/dashboard")
def sched1(start="NOW() - INTERVAL 5 MINUTE", end="NOW() + INTERVAL 2 HOUR"):
    db_exec(f"UPDATE elections SET status='scheduled', start_at={start}, end_at={end} WHERE id=1")
def add(name, dept, st, start, end):
    db_exec(f"INSERT INTO elections (name, department_id, school_year_id, start_at, end_at, status, created_by) VALUES (%s, %s, %s, {start}, {end}, %s, 1)", (name, dept, e1["y"], st))
    return fetch_one("SELECT id FROM elections WHERE name=%s", (name,))["id"]
def admin_notices(title_like): return fetch_one("SELECT COUNT(*) n FROM notifications WHERE title LIKE %s", (title_like,))["n"]

# ---------- 1) scheduled + start time reached -> opens by itself
db_exec("UPDATE candidates SET status='approved' WHERE election_id=1")   # the seed has one pending candidate, which (correctly) blocks opening
sched1(); db_exec("DELETE FROM notifications")
tick()
check(status(1) == "open", "scheduled election opens by itself when its start time arrives")
row = fetch_one("SELECT user_id, description FROM audit_logs WHERE action='election_opened' ORDER BY id DESC LIMIT 1")
check(row and row["user_id"] is None and "opened automatically" in row["description"], "audit log: opened by the system, with the reason", row)
check(fetch_one("SELECT COUNT(*) n FROM notifications WHERE title='Voting is open'")["n"] >= 1, "eligible students are notified that voting is open")
check(fetch_one("SELECT COUNT(*) n FROM notifications WHERE title LIKE 'Voting opened:%%' AND message LIKE '%%scheduled start time%%'")["n"] >= 2, "Super Admin and School Admin are notified it opened automatically")
cs = app.test_client(); login(cs, "2026-0002", "Student@123")
cands = fetch_all("SELECT id, position_id FROM candidates WHERE election_id=1 AND status='approved'"); form = {}; seen = set()
for cd in cands:
    if cd["position_id"] not in seen: form[f"position_{cd['position_id']}"] = str(cd["id"]); seen.add(cd["position_id"])
tok = csrf_from(cs.get("/vote/1").get_data(as_text=True)); r = cs.post("/vote/1/cast", data=dict(form, csrf_token=tok))
check(r.status_code == 302 and "/done" in r.headers["Location"], "a student can vote right after the automatic start")
logs = fetch_one("SELECT COUNT(*) n FROM audit_logs WHERE action='election_opened'")["n"]; tick()
check(fetch_one("SELECT COUNT(*) n FROM audit_logs WHERE action='election_opened'")["n"] == logs and status(1) == "open", "running again does not open or log twice")

# ---------- 2) things that must NOT be opened
later = add("Later", other, "scheduled", "NOW() + INTERVAL 1 DAY", "NOW() + INTERVAL 2 DAY")
draft = add("DraftPast", other, "draft", "NOW() - INTERVAL 1 HOUR", "NOW() + INTERVAL 3 HOUR")
tick()
check(status(later) == "scheduled", "a scheduled election before its start time stays scheduled")
check(status(draft) == "draft", "a DRAFT is never opened, even if its start time has passed")

# ---------- 3) period already over while still scheduled: not opened, admins told once
db_exec("DELETE FROM notifications"); logs = fetch_one("SELECT COUNT(*) n FROM audit_logs WHERE action='election_open_blocked'")["n"]
missed = add("Missed", other, "scheduled", "NOW() - INTERVAL 3 HOUR", "NOW() - INTERVAL 1 HOUR")
tick(); tick()
check(status(missed) == "scheduled", "an election whose whole period passed is not opened")
check(admin_notices("Election not opened: Missed") == 2, "Super Admin and School Admin get exactly one notice each (no repeats)", admin_notices("Election not opened: Missed"))
check(fetch_one("SELECT COUNT(*) n FROM audit_logs WHERE action='election_open_blocked'")["n"] == logs + 1, "one audit entry for it")
check("ended before it could be opened" in fetch_one("SELECT message FROM notifications WHERE title LIKE 'Election not opened: Missed' LIMIT 1")["message"], "the notice explains why")

# ---------- 4) blocked start: no approved candidate -> notice once -> fix -> opens by itself
db_exec("UPDATE elections SET status='draft' WHERE id=1"); db_exec("UPDATE elections SET status='closed' WHERE id=%s", (later,))
db_exec("DELETE FROM notifications"); db_exec("UPDATE candidates SET status='pending' WHERE election_id=1"); sched1()
tick(); tick(); tick()
check(status(1) == "scheduled", "blocked by a missing approved candidate: stays scheduled")
n = admin_notices("Election not opened: College%%")
check(n == 2, "admins told once about the blocker (not once per check)", n)
msg = fetch_one("SELECT message FROM notifications WHERE title LIKE 'Election not opened: College%%' LIMIT 1")["message"]
check("approved candidate" in msg, "the notice names the reason", msg)
db_exec("UPDATE candidates SET status='approved' WHERE election_id=1"); tick()
check(status(1) == "open", "after the problem is fixed the election opens by itself on the next check")
check(admin_notices("Election not opened: College%%") == 2, "no extra notice when it finally opens")

# ---------- 5) overlap with another election of the same department
db_exec("UPDATE elections SET status='draft' WHERE id=1"); db_exec("DELETE FROM notifications")
clash = add("Clash", e1["d"], "open", "NOW() - INTERVAL 1 HOUR", "NOW() + INTERVAL 4 HOUR"); sched1(); tick()
check(status(1) == "scheduled" and admin_notices("Election not opened: College%%") == 2, "overlapping election of the same department blocks it, with a notice")
check("overlaps" in fetch_one("SELECT message FROM notifications WHERE title LIKE 'Election not opened: College%%' LIMIT 1")["message"], "the notice says it overlaps")
db_exec("UPDATE elections SET status='closed' WHERE id=%s", (clash,)); tick(); check(status(1) == "open", "once the clash is gone it opens")

# ---------- 6) command line
db_exec("UPDATE elections SET status='scheduled' WHERE id=1")
out = subprocess.run([sys.executable, "close_due_elections.py"], capture_output=True, text=True, cwd=ROOT, env=dict(os.environ))
check("Opened 1 election(s)" in out.stdout and status(1) == "open", "close_due_elections.py also opens due elections", out.stdout + out.stderr[-300:])

# ---------- 7) the whole life cycle by the background thread, nobody clicking anything
db_exec("UPDATE elections SET status='scheduled', start_at=NOW() + INTERVAL 3 SECOND, end_at=NOW() + INTERVAL 12 SECOND WHERE id=1")
app.config["AUTO_CLOSE_THREAD"] = True; app.config["AUTO_CLOSE_INTERVAL"] = 5; auto_close._thread_started = False
auto_close.start_background_thread(app)
check(status(1) == "scheduled", "before the start time: still scheduled")
time.sleep(8.5); check(status(1) == "open", "the background thread opened it at the scheduled start (nobody on the site)")
time.sleep(9);   check(status(1) == "closed", "and closed it at the scheduled end")
raise SystemExit(summary())
