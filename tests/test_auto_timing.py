"""Timing of the automatic start/end: it must happen within about a second or two of the set time, not "sometime within
the polling interval", and the pages must refresh themselves at those moments."""
from helpers import *
import os, re, time
os.environ["WERKZEUG_RUN_MAIN"] = "true"
from app.elections import auto_close
app, c = new_client(); db_exec("UPDATE users SET must_change_password=0")
login(c, "superadmin", "SuperAdmin@123")
app.config["AUTO_CLOSE_THREAD"] = True
app.config["AUTO_CLOSE_INTERVAL"] = 15           # a LONG polling interval: precision must NOT depend on it
db_exec("UPDATE candidates SET status='approved' WHERE election_id=1")
def status(): return fetch_one("SELECT status FROM elections WHERE id=1")["status"]
def wait_for(wanted, limit):
    t = time.time()
    while time.time() - t < limit:
        if status() == wanted: return time.time() - t
        time.sleep(0.1)
    return None

# ---- 1) start-up catch-up: it was due while the app was "off"; the thread handles it right after starting, no request needed
db_exec("UPDATE elections SET status='scheduled', start_at=NOW()-INTERVAL 30 SECOND, end_at=NOW()+INTERVAL 1 HOUR WHERE id=1")
auto_close._thread_started = False; auto_close.start_background_thread(app)
lag = wait_for("open", 8)
check(lag is not None and lag < 4, f"start-up catch-up: an election that became due while the app was off opens within seconds of starting ({lag and round(lag, 1)}s)")

# ---- 2) a normal scheduled election, scheduled from the website (this also wakes the thread, whatever the polling interval)
db_exec("UPDATE elections SET status='draft', start_at=NOW()+INTERVAL 5 SECOND, end_at=NOW()+INTERVAL 11 SECOND WHERE id=1")
tok = csrf_from(c.get("/elections/1").get_data(as_text=True))
r = c.post("/elections/1/status/schedule", data={"csrf_token": tok}); check(r.status_code == 302 and status() == "scheduled", "election scheduled from the Elections page")
check(status() == "scheduled", "not opened before its start time")
t_sched = time.time()
lag_open = wait_for("open", 12)
check(lag_open is not None, "it opened by itself", lag_open)
row = fetch_one("SELECT TIMESTAMPDIFF(SECOND, e.start_at, a.created_at) AS late FROM elections e JOIN audit_logs a ON a.action='election_opened' AND a.description LIKE CONCAT('%%', e.name, '%%') WHERE e.id=1 ORDER BY a.id DESC LIMIT 1")
check(row["late"] is not None and 0 <= row["late"] <= 2, f"it opened within 2 seconds of its start time (audit log says {row['late']}s after)", row)
lag_close = wait_for("closed", 12)
check(lag_close is not None, "it closed by itself")
row = fetch_one("SELECT TIMESTAMPDIFF(SECOND, e.end_at, a.created_at) AS late FROM elections e JOIN audit_logs a ON a.action='election_closed' AND a.description LIKE CONCAT('%%', e.name, '%%') WHERE e.id=1 ORDER BY a.id DESC LIMIT 1")
check(row["late"] is not None and 0 <= row["late"] <= 2, f"it closed within 2 seconds of its end time (audit log says {row['late']}s after)", row)
check(time.time() - t_sched < 20, "the whole schedule->open->close cycle ran on time with a 15-second polling interval")

# ---- 3) editing the dates also wakes the checker
db_exec("UPDATE elections SET status='draft', start_at=NOW()+INTERVAL 1 DAY, end_at=NOW()+INTERVAL 2 DAY WHERE id=1")
c.post("/elections/1/status/schedule", data={"csrf_token": tok})
f = {"name": "College Student Council Election 2026", "department_id": str(fetch_one("SELECT department_id d FROM elections WHERE id=1")["d"]), "school_year_id": str(fetch_one("SELECT school_year_id y FROM elections WHERE id=1")["y"]),
     "start_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 6)), "end_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 600))}
db_exec("UPDATE elections SET start_at=NOW()+INTERVAL 6 SECOND, end_at=NOW()+INTERVAL 600 SECOND WHERE id=1")
auto_close.wake()
check(wait_for("open", 12) is not None, "after the dates are changed it still opens at the new start time")
db_exec("UPDATE elections SET status='closed' WHERE id=1")

# ---- 4) pages refresh themselves at the next start/end (seconds come from the server clock)
db_exec("UPDATE elections SET status='scheduled', start_at=NOW()+INTERVAL 90 SECOND, end_at=NOW()+INTERVAL 1 HOUR WHERE id=1")
h = c.get("/elections/1").get_data(as_text=True)
m = re.search(r"var due = Date\.now\(\) \+ \((\d+) \+ 2\) \* 1000", h)
check(m and 80 <= int(m.group(1)) <= 90, "Election page reloads itself at the start time (server-measured seconds)", m and m.group(1))
db_exec("UPDATE elections SET status='open', start_at=NOW()-INTERVAL 1 HOUR, end_at=NOW()+INTERVAL 75 SECOND WHERE id=1")
m = re.search(r"var due = Date\.now\(\) \+ \((\d+) \+ 2\)", c.get("/elections/1").get_data(as_text=True))
check(m and 65 <= int(m.group(1)) <= 75, "an open election's page reloads itself at the end time", m and m.group(1))
db_exec("UPDATE elections SET status='draft' WHERE id=1")
check("var due" not in c.get("/elections/1").get_data(as_text=True), "a draft page has no timer")
db_exec("UPDATE elections SET status='scheduled', start_at=NOW()+INTERVAL 40 DAY, end_at=NOW()+INTERVAL 41 DAY WHERE id=1")
check("var due" not in c.get("/elections/1").get_data(as_text=True), "very distant start: no timer (browser timers overflow after ~24 days)")
cs = app.test_client(); login(cs, "2026-0002", "Student@123")
db_exec("UPDATE elections SET status='scheduled', start_at=NOW()+INTERVAL 60 SECOND, end_at=NOW()+INTERVAL 1 HOUR WHERE id=1")
m = re.search(r"var due = Date\.now\(\) \+ \((\d+) \+ 2\)", cs.get("/vote").get_data(as_text=True))
check(m and 50 <= int(m.group(1)) <= 60, "the student's My Elections page reloads itself when voting starts", m and m.group(1))
db_exec("UPDATE elections SET status='open', start_at=NOW()-INTERVAL 1 HOUR, end_at=NOW()+INTERVAL 50 SECOND WHERE id=1")
m = re.search(r"var due = Date\.now\(\) \+ \((\d+) \+ 2\)", cs.get("/vote").get_data(as_text=True))
check(m and 40 <= int(m.group(1)) <= 50, "...and when voting ends", m and m.group(1))

# ---- 5) the banner when it cannot open
db_exec("UPDATE elections SET status='scheduled', start_at=NOW()-INTERVAL 5 MINUTE, end_at=NOW()+INTERVAL 1 HOUR WHERE id=1")
db_exec("UPDATE candidates SET status='pending' WHERE election_id=1 AND id=(SELECT id FROM (SELECT MIN(id) id FROM candidates WHERE election_id=1) x)")
h = c.get("/elections/1").get_data(as_text=True)
check("could not open" in h and "pending review" in h and "keeps trying" in h, "Election page explains why it did not open (pending candidate) and that the system keeps trying")
pend = fetch_one("SELECT id FROM candidates WHERE election_id=1 AND status='pending'")["id"]
t2 = csrf_from(c.get(f"/candidates/{pend}").get_data(as_text=True))
c.post(f"/candidates/{pend}/review/approve", data={"csrf_token": t2, "remarks": ""})       # the admin approves the candidate on the website
check(wait_for("open", 4) is not None, "...and it opens by itself right after the problem is fixed (approving the candidate wakes the checker)")
check("could not open" not in c.get("/elections/1").get_data(as_text=True), "banner disappears once it is open")
raise SystemExit(summary())
