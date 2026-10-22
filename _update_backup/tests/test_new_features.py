from helpers import *
import io, re, datetime as dt
from werkzeug.security import check_password_hash
app, c = new_client(); db_exec("UPDATE users SET must_change_password=0")
login(c, "superadmin", "SuperAdmin@123")
dep = fetch_one("SELECT id FROM departments WHERE code='COL'")["id"]; yr = fetch_one("SELECT id FROM school_years WHERE status='active'")["id"]
now = dt.datetime.now(); fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M")
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64

def post(url, data, **kw): r = ajax_post(c, url, data, **kw); return r.status_code, r.get_json()

# ============================================================ 1) Add User: roles
h = ajax_get(c, "/super-admin/users/new").get_data(as_text=True)
roles = re.findall(r'data-value="(super_admin|school_admin|council_officer|student)"', h)
check("super_admin" not in roles and set(roles) == {"school_admin", "council_officer", "student"}, "role dropdown: no Super Admin, Student added", roles)
check('data-show-role="student"' in h and 'name="student_number"' in h and 'name="department_id"' in h, "Student role reveals the student fields")
for f in ["birthdate", "contact_number", "barangay", "purok_street", "city_municipality"]:
    check(f'name="{f}"' in h, f"Add User form has the {f} field")
check("Nueva Ecija" in h and h.count('data-icon="fa-location-dot"') == 32, "province Nueva Ecija shown; city list has all 32 cities and municipalities")

# ============================================================ 2) staff user: personal details
staff = {"username": "staff1", "first_name": "Ana", "middle_name": "", "last_name": "Reyes", "email": "ana.reyes@gmail.com", "role": "school_admin",
         "password": "Passw0rd123", "confirm_password": "Passw0rd123"}
s, j = post("/super-admin/users/new", dict(staff, role="super_admin")); check(s == 422 and "role" in j["errors"], "server refuses to create a Super Admin")
for field in ["birthdate", "contact_number", "barangay", "purok_street", "city_municipality"]:
    data = dict(staff, **{k: v for k, v in PERSONAL.items() if k != field}); s, j = post("/super-admin/users/new", data, personal=False)
    check(s == 422 and field in j["errors"], f"missing {field} is rejected")
bad = {"city_municipality": "Manila", "birthdate": "2999-01-01", "contact_number": "12345"}
for field, value in bad.items():
    s, j = post("/super-admin/users/new", dict(staff, **{field: value})); check(s == 422 and field in j["errors"], f"invalid {field} ({value}) rejected")
s, j = post("/super-admin/users/new", dict(staff, birthdate=(now - dt.timedelta(days=365 * 2)).strftime("%Y-%m-%d"))); check(s == 422 and "birthdate" in j["errors"], "a 2-year-old is rejected (minimum age 5)")
s, j = post("/super-admin/users/new", dict(staff, city_municipality="cabanatuan", contact_number="+63 917-123-4567", barangay="  Sta.   Rosa ")); check(s == 200, "valid staff user created", j)
row = fetch_one("SELECT barangay, purok_street, city_municipality, province, birthdate, contact_number FROM users WHERE username='staff1'")
check(row["city_municipality"] == "Cabanatuan City" and row["province"] == "Nueva Ecija", "city normalised to the official name; province is Nueva Ecija", row)
check(row["contact_number"] == "09171234567" and str(row["birthdate"]) == "2008-05-14" and row["barangay"] == "Sta. Rosa", "contact number stored as 09XXXXXXXXX, birthday as a date, spaces trimmed", row)
check(fetch_one("SELECT COUNT(*) n FROM users WHERE username LIKE 'staff%%'")["n"] == 1, "rejected submissions created nothing")

# ============================================================ 3) student created from the Users form
st = {"role": "student", "student_number": "80555001", "first_name": "Khen", "middle_name": "D", "last_name": "Rod", "email": "khenrodc@gmail.com",
      "department_id": str(dep), "year_level": "1st Year", "section": "A", "school_year_id": str(yr), "password": "Passw0rd123", "confirm_password": "Passw0rd123"}
for field in ["student_number", "department_id", "year_level", "section", "school_year_id"]:
    s, j = post("/super-admin/users/new", {k: v for k, v in st.items() if k != field}); check(s == 422 and field in j["errors"], f"student: missing {field} rejected")
s, j = post("/super-admin/users/new", dict(st, student_number="8055-5001")); check(s == 422 and "student_number" in j["errors"], "student: Student ID must be 8 digits")
s, j = post("/super-admin/users/new", dict(st, email="x@yahoo.com")); check(s == 422 and "email" in j["errors"], "student: email domain rule applies")
s, j = post("/super-admin/users/new", dict(st, email="80000009@holycross.edu.ph")); check(s == 422 and "does not match" in j["errors"]["email"], "student: school email must carry their own number")
s, j = post("/super-admin/users/new", dict(st, city_municipality="Manila")); check(s == 422 and "city_municipality" in j["errors"], "student: personal details are validated too")
check(fetch_one("SELECT COUNT(*) n FROM students WHERE student_number='80555001'")["n"] == 0, "no student saved by rejected requests")
s, j = post("/super-admin/users/new", st); check(s == 200 and j["ok"], "student account created from Add User", j)
u = fetch_one("SELECT u.id, u.username, u.email, u.full_name, u.must_change_password, u.contact_number, r.name role FROM users u JOIN roles r ON r.id=u.role_id WHERE u.username='80555001'")
check(u and u["role"] == "student" and u["must_change_password"] == 1 and u["email"] == "khenrodc@gmail.com" and u["full_name"] == "Khen D Rod", "user row: student role, username = Student ID, must change password", u)
stu = fetch_one("SELECT student_number, department_id, user_id FROM students WHERE student_number='80555001'")
check(stu and stu["user_id"] == u["id"] and stu["department_id"] == dep, "student record created and linked to the account")
check(login(app.test_client(), "80555001", "Passw0rd123"), "the new student can log in with the password set in the form")
s, j = post("/super-admin/users/new", st); check(s == 422 and "student_number" in j["errors"], "duplicate Student ID rejected")
s, j = post("/super-admin/users/new", dict(st, student_number="80555002", email="80555002@holycross.edu.ph")); check(s == 200, "student with own school email accepted", j)

# ============================================================ 4) edit user / students module / profile
uid = fetch_one("SELECT id FROM users WHERE username='staff1'")["id"]
h = ajax_get(c, f"/super-admin/users/{uid}/edit").get_data(as_text=True)
check('value="2008-05-14"' in h and 'value="09171234567"' in h and 'value="Sta. Rosa"' in h, "Edit User is pre-filled with birthday, contact number and address")
s, j = post(f"/super-admin/users/{uid}/edit", {"first_name": "Ana", "last_name": "Reyes", "email": "ana.reyes@gmail.com", "role": "school_admin"}, personal=False); check(s == 422 and "birthdate" in j["errors"], "edit also requires the personal details")
s, j = post(f"/super-admin/users/{uid}/edit", {"first_name": "Ana", "last_name": "Reyes", "email": "ana.reyes@gmail.com", "role": "school_admin", "contact_number": "0922 000 1111", "city_municipality": "Gapan City"}); check(s == 200, "edit saves new personal details", j)
check(fetch_one("SELECT contact_number, city_municipality FROM users WHERE id=%s", (uid,)) == {"contact_number": "09220001111", "city_municipality": "Gapan City"}, "edited values stored")
s, j = post(f"/super-admin/users/{uid}/edit", {"first_name": "Ana", "last_name": "Reyes", "email": "ana.reyes@gmail.com", "role": "super_admin"}); check(s == 422 and "role" in j["errors"], "cannot promote someone to Super Admin by editing")
sid = fetch_one("SELECT id FROM students WHERE student_number='80555002'")["id"]
sb = {"first_name": "Mia", "last_name": "Cruz", "email": "80555002@holycross.edu.ph", "department_id": str(dep), "year_level": "1st Year", "section": "B", "school_year_id": str(yr)}
s, j = post(f"/students/{sid}/edit", sb, personal=False); check(s == 422 and "birthdate" in j["errors"], "Students edit requires the personal details")
s, j = post(f"/students/{sid}/edit", sb); check(s == 200, "Students edit saves with personal details", j)
s, j = post("/students/new", dict(sb, student_number="80555003", email="80555003@holycross.edu.ph"), personal=False); check(s == 422 and "contact_number" in j["errors"], "Students add requires the personal details")
s, j = post("/students/new", dict(sb, student_number="80555003", email="80555003@holycross.edu.ph")); check(s == 200, "Students add saves with personal details", j)
cs = app.test_client(); login(cs, "schooladmin", "SchoolAdmin@123")
s = ajax_post(cs, "/profile/edit", {"first_name": "Sam", "last_name": "Admin", "email": "sam@gmail.com"}, personal=False); check(s.status_code == 422 and "birthdate" in s.get_json()["errors"], "Edit Profile requires the personal details")
s = ajax_post(cs, "/profile/edit", {"first_name": "Sam", "last_name": "Admin", "email": "sam@gmail.com", "barangay": "Poblacion", "purok_street": "Rizal Street", "city_municipality": "Santa Rosa"}); check(s.status_code == 200, "Edit Profile saves personal details")
page = cs.get("/profile").get_data(as_text=True)
check("May 14, 2008" in page and "09171234567" in page and "Rizal Street, Brgy. Poblacion, Santa Rosa, Nueva Ecija" in page, "Profile page shows birthday, contact number and the full address")

# ============================================================ 5) Super Admin works like an officer
council = fetch_one("SELECT id, name FROM councils WHERE status='active' ORDER BY id LIMIT 1")
ev = {"council_id": str(council["id"]), "title": "Admin Fair", "description": "A fair organised by the admin", "objectives": "Bring the school together",
      "location": "Gym", "event_start": fmt(now + dt.timedelta(days=30)), "event_end": fmt(now + dt.timedelta(days=30, hours=4)), "supporting_info": ""}
h = ajax_get(c, "/events/new").get_data(as_text=True); check("New Event Proposal" in h and str(council["id"]) in h, "Super Admin can open New Event")
check("New</" in c.get("/events").get_data(as_text=True) or "data-modal-url" in c.get("/events").get_data(as_text=True), "Super Admin sees the New button on the Events list")
s, j = post("/events/new", ev); check(s == 200 and "/events/" in j["redirect"], "Super Admin created an event proposal", j)
evid = fetch_one("SELECT id, submitted_by FROM events WHERE title='Admin Fair'")
check(evid["submitted_by"] == fetch_one("SELECT id FROM users WHERE username='superadmin'")["id"], "the Super Admin is recorded as the author")
check(ajax_get(c, f"/events/{evid['id']}/edit").status_code == 200 and "Edit Event" in ajax_get(c, f"/events/{evid['id']}/edit").get_data(as_text=True), "Super Admin can edit their own draft")
r = ajax_post(c, f"/events/{evid['id']}/submit", {}); check(fetch_one("SELECT status FROM events WHERE id=%s", (evid["id"],))["status"] == "submitted", "Super Admin can submit their proposal")
r = ajax_post(c, f"/events/{evid['id']}/approve", {}); check(fetch_one("SELECT status FROM events WHERE id=%s", (evid["id"],))["status"] == "submitted", "separation of duties: the Super Admin cannot approve their OWN proposal")
r = ajax_post(cs, f"/events/{evid['id']}/approve", {}); check(fetch_one("SELECT status FROM events WHERE id=%s", (evid["id"],))["status"] == "approved", "a School Admin can approve it")
pj = {"council_id": str(council["id"]), "title": "Admin Project", "description": "A project from admin", "objectives": "Improve the campus", "start_date": (now + dt.timedelta(days=5)).strftime("%Y-%m-%d"), "end_date": (now + dt.timedelta(days=9)).strftime("%Y-%m-%d")}
s, j = post("/projects/new", pj); check(s == 200, "Super Admin created a project proposal", j)
# budgets and expenses for the approved event
h = ajax_get(c, "/budgets/new").get_data(as_text=True); key = re.search(r'data-value="(event:\d+)"', h)
check(key is not None, "Super Admin can pick the approved event when requesting a budget")
s, j = post("/budgets/new", {"activity": key.group(1), "requested_amount": "7500", "breakdown": "Food 5000, Prints 2500", "description": "Funds for the fair"}); check(s == 200, "Super Admin requested a budget", j)
s, j = post("/expenses/new", {"activity": key.group(1), "amount": "250.50", "expense_date": now.strftime("%Y-%m-%d"), "description": "Snacks"}); check(s == 200, "Super Admin recorded an expense", j)
# documents and meetings
doc = {"council_id": str(council["id"]), "title": "Fair Permit", "category": "other", "description": "", "link": ""}
t = csrf_from(c.get("/documents/new").get_data(as_text=True))
r = c.post("/documents/new", data=dict(doc, csrf_token=t, file=(io.BytesIO(PNG), "permit.png")), content_type="multipart/form-data"); check(r.status_code == 302, "Super Admin uploaded a document", r.status_code)
check(fetch_one("SELECT COUNT(*) n FROM documents WHERE title='Fair Permit'")["n"] == 1, "document saved")
t = csrf_from(c.get("/meetings/new").get_data(as_text=True))
mt = {"council_id": str(council["id"]), "title": "Planning Meeting", "meeting_at": fmt(now + dt.timedelta(days=2)), "location": "Room 1", "agenda": "Plan the fair", "csrf_token": t}
r = c.post("/meetings/new", data=mt); check(r.status_code == 302, "Super Admin scheduled a meeting", r.status_code)
check(fetch_one("SELECT COUNT(*) n FROM meetings WHERE title='Planning Meeting'")["n"] == 1, "meeting saved")
# others keep their limits
check(ajax_get(cs, "/events/new").status_code == 403, "School Admin still cannot create officer proposals")
cst = app.test_client(); login(cst, "2026-0002", "Student@123"); check(ajax_get(cst, "/budgets/new").status_code == 403, "students still cannot")
co = app.test_client(); login(co, "officer1", "Officer@123"); check(ajax_get(co, "/events/new").status_code == 200, "council officers still can")

# ============================================================ 6) Super Admin votes
other = fetch_one("SELECT id FROM departments WHERE id<>1 AND id<>%s ORDER BY id LIMIT 1", (dep,))["id"]
db_exec("UPDATE elections SET status='open', start_at=NOW()-INTERVAL 1 HOUR, end_at=NOW()+INTERVAL 5 HOUR WHERE id=1")
supid = fetch_one("SELECT id FROM users WHERE username='superadmin'")["id"]
page = c.get("/vote").get_data(as_text=True); check(c.get("/vote").status_code == 200 and "College Student Council Election" in page, "Super Admin sees My Elections with the election of any department")
check("Vote now" in page and "any department" in page, "the election shows Vote now and the Super Admin wording")
check('href="/vote"' in c.get("/super-admin/dashboard").get_data(as_text=True), "sidebar shows My Elections for the Super Admin")
before = fetch_one("SELECT eligible_voters e, votes_cast v FROM v_election_participation WHERE election_id=1")
cands = fetch_all("SELECT id, position_id FROM candidates WHERE election_id=1 AND status='approved'")
form = {}; seen = set()
for cand in cands:
    if cand["position_id"] not in seen: form[f"position_{cand['position_id']}"] = str(cand["id"]); seen.add(cand["position_id"])
r = c.get("/vote/1"); check(r.status_code == 200 and "Choose one candidate per position" in r.get_data(as_text=True), "ballot page opens for the Super Admin")
tok = csrf_from(r.get_data(as_text=True))
r = c.post("/vote/1/review", data=dict(form, csrf_token=tok)); check(r.status_code == 200, "review step works")
r = c.post("/vote/1/cast", data=dict(form, csrf_token=tok)); check(r.status_code == 302 and "/done" in r.headers["Location"], "Super Admin cast a ballot", r.status_code)
ballot = fetch_one("SELECT student_id, voter_user_id FROM ballots WHERE election_id=1 AND voter_user_id=%s", (supid,))
check(ballot and ballot["student_id"] is None, "ballot stored against the Super Admin account, not a student")
check(c.get("/vote/1/done").status_code == 200, "confirmation page shows")
n = fetch_one("SELECT COUNT(*) n FROM ballots")["n"]; c.post("/vote/1/cast", data=dict(form, csrf_token=tok))
check(fetch_one("SELECT COUNT(*) n FROM ballots")["n"] == n, "a second vote is refused: one ballot per election")
after = fetch_one("SELECT eligible_voters e, votes_cast v FROM v_election_participation WHERE election_id=1")
check(after["v"] == before["v"] + 1, "turnout counts the Super Admin's ballot")
check(int(before["e"]) >= 1 + int(fetch_one("SELECT COUNT(*) n FROM students WHERE department_id=%s AND school_year_id=%s AND status='active'", (dep, yr))["n"]), "eligible voters include the Super Admin")
log = fetch_one("SELECT description FROM audit_logs WHERE action='ballot_cast' AND user_id=%s ORDER BY id DESC LIMIT 1", (supid,))
check(log and "College" in log["description"] and not re.search(r"candidate|ballot id|\d{3,}", log["description"].replace("2026", "")), "audit log says THAT they voted, not what", log)
# an election of another department, and the closed-election rule
db_exec("INSERT INTO elections (name, department_id, school_year_id, start_at, end_at, status, created_by) VALUES ('Other Dept', %s, %s, NOW()-INTERVAL 1 HOUR, NOW()+INTERVAL 3 HOUR, 'open', 1)", (other, yr))
oid = fetch_one("SELECT id FROM elections WHERE name='Other Dept'")["id"]
check(c.get(f"/vote/{oid}").status_code == 200, "Super Admin can open the ballot of another department's election (deliberate exception)")
db_exec("UPDATE elections SET status='closed' WHERE id=%s", (oid,))
r = c.get(f"/vote/{oid}"); check(r.status_code == 302, "closed election: ballot refused")
cs2 = app.test_client(); login(cs2, "schooladmin", "SchoolAdmin@123"); check(cs2.get("/vote").status_code == 403, "School Admin still cannot vote (no student record)")
co2 = app.test_client(); login(co2, "officer1", "Officer@123"); check(co2.get("/vote").status_code == 200, "officers (who are students) are unaffected")
raise SystemExit(summary())
