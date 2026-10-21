from helpers import *
import io, re, datetime as dt
app, c = new_client()
db_exec("UPDATE users SET must_change_password=0")
login(c, "superadmin", "SuperAdmin@123")
dep = fetch_one("SELECT id FROM departments WHERE code='COL'")["id"]
dep2 = fetch_one("SELECT id FROM departments WHERE code<>'COL' ORDER BY id LIMIT 1")["id"]
yr = fetch_one("SELECT id FROM school_years WHERE status='active'")["id"]
fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M")
now = dt.datetime.now()

def modal(client, url): 
    r = ajax_get(client, url); return r.status_code, r.get_data(as_text=True)

# ---------------- POSITIONS
s, h = modal(c, "/positions/new"); check(s == 200 and "New Position" in h and "data-modal-form" in h, "New Position opens as a modal")
check(c.get("/positions/new").status_code == 302, "direct URL goes back to the list")
r = ajax_post(c, "/positions/new", {"name": "", "description": "", "seats": "1"}); check(r.status_code == 422 and r.get_json()["errors"]["_form"], "empty position rejected with a message")
before = fetch_one("SELECT COUNT(*) n FROM positions")["n"]
r = ajax_post(c, "/positions/new", {"name": "Sergeant at Arms", "description": "Keeps order", "seats": "2"}); check(r.status_code == 200 and r.get_json()["ok"], "position created", r.get_json())
check(fetch_one("SELECT COUNT(*) n FROM positions")["n"] == before + 1 and fetch_one("SELECT seats FROM positions WHERE name='Sergeant at Arms'")["seats"] == 2, "position saved with seats")
r = ajax_post(c, "/positions/new", {"name": "Sergeant at Arms", "description": "", "seats": "1"}); check(r.status_code == 422, "duplicate position name rejected")
pid = fetch_one("SELECT id FROM positions WHERE name='Sergeant at Arms'")["id"]
s, h = modal(c, f"/positions/{pid}/edit"); check(s == 200 and "Edit Position" in h and 'value="Sergeant at Arms"' in h, "Edit Position modal pre-filled")
r = ajax_post(c, f"/positions/{pid}/edit", {"name": "Sergeant-at-Arms", "description": "", "seats": "1"}); check(r.status_code == 200, "position edited")
h = c.get("/positions").get_data(as_text=True); check('id="list-region"' in h and "data-modal-url" in h, "positions list refreshes in place")

# ---------------- ELECTIONS
s, h = modal(c, "/elections/new"); check(s == 200 and "New Election" in h and "Voting starts" in h, "New Election opens as a modal")
e = {"name": "Test Election", "department_id": str(dep2), "school_year_id": str(yr), "start_at": fmt(now + dt.timedelta(days=10)), "end_at": fmt(now + dt.timedelta(days=11))}
r = ajax_post(c, "/elections/new", dict(e, name="")); check(r.status_code == 422, "election without a name rejected")
r = ajax_post(c, "/elections/new", dict(e, end_at=e["start_at"])); check(r.status_code == 422, "end not after start rejected")
n0 = fetch_one("SELECT COUNT(*) n FROM elections")["n"]
r = ajax_post(c, "/elections/new", e); j = r.get_json()
check(r.status_code == 200 and j["ok"] and "/elections/" in j["redirect"], "election created, response sends you to its page", j)
check(fetch_one("SELECT COUNT(*) n FROM elections")["n"] == n0 + 1, "election row saved")
eid = fetch_one("SELECT id FROM elections WHERE name='Test Election'")["id"]
check(c.get(j["redirect"]).status_code == 200, "election detail page loads after creation")
s, h = modal(c, f"/elections/{eid}/edit"); check(s == 200 and "Edit Election" in h and 'value="Test Election"' in h, "Edit Election modal pre-filled")
r = ajax_post(c, f"/elections/{eid}/edit", dict(e, name="Test Election 2")); check(r.status_code == 200 and r.get_json().get("reload"), "election edited (page reloads)")
s, h = modal(c, "/elections/1/edit"); check(s == 200 and "Only draft or scheduled elections can be edited" in h, "open election: edit explains why instead of failing")
cs = app.test_client(); login(cs, "2026-0002", "Student@123")
check(ajax_get(cs, "/elections/new").status_code == 403 and ajax_post(cs, "/elections/new", e).status_code == 403, "student cannot create elections")

# ---------------- COUNCILS
s, h = modal(c, "/councils/new"); check(s == 200 and "New Council" in h and "Term starts" in h, "New Council opens as a modal")
cn = {"name": "Test Council", "department_id": str(dep2), "school_year_id": str(yr), "term_start": "2026-06-01", "term_end": "2027-05-31", "election_id": ""}
r = ajax_post(c, "/councils/new", dict(cn, name="")); check(r.status_code == 422, "council without a name rejected")
r = ajax_post(c, "/councils/new", dict(cn, term_end="2026-01-01")); check(r.status_code == 422, "term end before start rejected")
r = ajax_post(c, "/councils/new", cn); j = r.get_json(); check(r.status_code == 200 and "/councils/" in j.get("redirect", ""), "council created", j)
cid = fetch_one("SELECT id FROM councils WHERE name='Test Council'")["id"]
s, h = modal(c, f"/councils/{cid}/edit"); check(s == 200 and "Edit Council" in h, "Edit Council modal opens")
r = ajax_post(c, f"/councils/{cid}/edit", dict(cn, name="Test Council B")); check(r.status_code == 200, "council edited")

# ---------------- EVENTS / PROJECTS (officer)
co = app.test_client(); login(co, "officer1", "Officer@123")
s, h = modal(co, "/events/new"); check(s == 200 and "New Event Proposal" in h and "Location" in h, "New Event opens as a modal")
council_id = re.search(r'name="council_id" value="(\d+)"', h).group(1)      # the form carries this as a hidden field
ev = {"council_id": council_id, "title": "Foundation Day", "description": "Celebration of the school", "objectives": "Build school unity", "location": "Gym", "event_start": fmt(now + dt.timedelta(days=20)), "event_end": fmt(now + dt.timedelta(days=20, hours=4)), "supporting_info": ""}
r = ajax_post(co, "/events/new", dict(ev, title="")); check(r.status_code == 422, "event without title rejected")
r = ajax_post(co, "/events/new", dict(ev, event_end=ev["event_start"])); check(r.status_code == 422, "event end not after start rejected")
r = ajax_post(co, "/events/new", ev); j = r.get_json(); check(r.status_code == 200 and "/events/" in j["redirect"], "event saved as draft", j)
check(fetch_one("SELECT status FROM events WHERE title='Foundation Day'")["status"] == "draft", "event stored as draft")
evid = fetch_one("SELECT id FROM events WHERE title='Foundation Day'")["id"]
s, h = modal(co, f"/events/{evid}/edit"); check(s == 200 and "Edit Event Proposal" in h, "Edit Event modal opens")
r = ajax_post(co, f"/events/{evid}/edit", dict(ev, title="Foundation Day 2026")); check(r.status_code == 200, "event edited")
s, h = modal(co, "/projects/new"); check(s == 200 and "New Project Proposal" in h, "New Project opens as a modal")
pj = {"council_id": council_id, "title": "Clean-up Drive", "description": "Campus clean-up", "objectives": "Keep campus clean", "start_date": (now + dt.timedelta(days=5)).strftime("%Y-%m-%d"), "end_date": (now + dt.timedelta(days=6)).strftime("%Y-%m-%d")}
r = ajax_post(co, "/projects/new", dict(pj, end_date="2020-01-01")); check(r.status_code == 422, "project end before start rejected")
r = ajax_post(co, "/projects/new", pj); check(r.status_code == 200 and "/projects/" in r.get_json()["redirect"], "project saved as draft")
cs_admin = app.test_client(); login(cs_admin, "schooladmin", "SchoolAdmin@123")
check(ajax_get(cs, "/events/new").status_code == 403, "student cannot open New Event")
check(ajax_get(cs_admin, "/events/new").status_code == 403, "School Admin cannot create officer proposals (unchanged rule)")

# ---------------- BUDGETS / EXPENSES
s, h = modal(co, "/budgets/new"); check(s == 200 and "No approved activity yet" in h, "no approved activity -> clear explanation modal (no crash)")
db_exec("UPDATE events SET status='approved' WHERE id=%s", (evid,))
s, h = modal(co, "/budgets/new"); check(s == 200 and "New Budget" in h and "Requested amount" in h and 'type="file"' in h, "New Budget opens as a modal with file upload")
key = re.search(r'data-value="(event:\d+)"', h).group(1)
bd = {"activity": key, "requested_amount": "5000", "breakdown": "Food 3000, Prints 2000", "description": "Funds for the event"}
r = ajax_post(co, "/budgets/new", dict(bd, requested_amount="abc")); check(r.status_code == 422, "invalid amount rejected")
r = ajax_post(co, "/budgets/new", dict(bd, activity="event:99999")); check(r.status_code == 422, "someone else's/unknown activity rejected")
r = ajax_post(co, "/budgets/new", bd); j = r.get_json(); check(r.status_code == 200 and "/budgets/" in j["redirect"], "budget saved as draft", j)
bid = fetch_one("SELECT id FROM budget_requests ORDER BY id DESC LIMIT 1")["id"] if fetch_one("SHOW TABLES LIKE 'budget_requests'") else None
s, h = modal(co, "/expenses/new"); check(s == 200 and "New Expense" in h and "Receipt" in h, "New Expense opens as a modal")
ex = {"activity": key, "amount": "350.50", "expense_date": now.strftime("%Y-%m-%d"), "description": "Snacks"}
r = ajax_post(co, "/expenses/new", dict(ex, amount="-5")); check(r.status_code == 422, "negative expense rejected")
r = ajax_post(co, "/expenses/new", dict(ex), {"document": (io.BytesIO(b"not a real pdf"), "r.pdf", "application/pdf")}); check(r.status_code == 422, "fake receipt rejected by the server")
r = ajax_post(co, "/expenses/new", ex); j = r.get_json(); check(r.status_code == 200 and "/expenses/" in j["redirect"], "expense saved as draft", j)
exid = int(re.search(r"/expenses/(\d+)", j["redirect"]).group(1))
s, h = modal(co, f"/expenses/{exid}/edit"); check(s == 200 and "Edit Expense" in h and 'value="Snacks"' in h, "Edit Expense modal pre-filled")
r = ajax_post(co, f"/expenses/{exid}/edit", dict(ex, description="Snacks and water")); check(r.status_code == 200, "expense edited")
check(ajax_get(cs, "/budgets/new").status_code == 403, "student cannot open New Budget")

# ---------------- generic: every list page still renders with the new buttons
for u in ["/elections", "/positions", "/councils", "/events", "/projects", "/budgets", "/expenses"]:
    cl = co if u in ("/events", "/projects", "/budgets", "/expenses") else c
    h = cl.get(u).get_data(as_text=True); check(cl.get(u).status_code == 200 and "data-modal-url" in h, f"{u} renders with modal buttons")
raise SystemExit(summary())
