from helpers import *
app, c = new_client()
login(c, "superadmin", "SuperAdmin@123")
dep = fetch_one("SELECT id FROM departments WHERE code='COL'")["id"]
yr = fetch_one("SELECT id FROM school_years WHERE status='active'")["id"]
base = {"student_number": "80281999", "first_name": "Maria", "middle_name": "", "last_name": "Santos", "email": "80281999@holycross.edu.ph",
        "department_id": str(dep), "year_level": "1st Year", "section": "A", "school_year_id": str(yr)}
def post(**o):
    d = dict(base); d.update(o); r = ajax_post(c, "/students/new", d); return r.status_code, r.get_json()

r = ajax_get(c, "/students/new"); h = r.get_data(as_text=True)
check(r.status_code == 200 and "Student ID" in h and "data-year-map" in h, "Add Student opens as a modal")
check(c.get("/students/new").status_code == 302, "plain navigation redirects to list")
for sid in ["8028-1999", "8028199", "802819999", "80A81999", "8028 1999", ""]:
    s, j = post(student_number=sid, email=sid + "@holycross.edu.ph")
    check(s == 422 and "student_number" in j["errors"], f"Student ID {sid!r} rejected")
s, j = post(email=""); check(s == 422 and "email" in j["errors"], "email required for students")
s, j = post(email="80281999@yahoo.com"); check(s == 422 and "accepted" in j["errors"]["email"], "other domains rejected")
s, j = post(email="80382024@holycross.edu.ph"); check(s == 422 and "does not match" in j["errors"]["email"], "email number must equal Student ID")
s, j = post(email="8028199@holycross.edu.ph"); check(s == 422 and "email" in j["errors"], "7-digit email rejected")
check(fetch_one("SELECT id FROM students WHERE student_number='80281999'") is None, "no partial records from rejected requests")
s, j = post(); check(s == 200 and j["ok"] and "temp-pw" in j["html_result"], "valid student created, temp password shown once", j)
row = fetch_one("SELECT u.email, u.first_name, u.last_name, u.full_name, u.username FROM users u JOIN students s ON s.user_id=u.id WHERE s.student_number='80281999'")
check(row and row["email"] == "80281999@holycross.edu.ph" and row["username"] == "80281999" and row["full_name"] == "Maria Santos", "account + email + names stored", row)
check(fetch_one("SELECT student_number FROM students WHERE student_number='80281999'")["student_number"] == "80281999", "Student ID kept as a string")
s, j = post(); check(s == 422 and "already" in j["errors"]["student_number"], "duplicate Student ID rejected")
s, j = post(student_number="00000123", email="00000123@holycross.edu.ph")
check(s == 200, "leading zeros preserved", j)
check(fetch_one("SELECT student_number FROM students WHERE student_number='00000123'") is not None, "00000123 stored with zeros")
sid = fetch_one("SELECT id FROM students WHERE student_number='80281999'")["id"]
r = ajax_post(c, f"/students/{sid}/edit", dict(base, first_name="Mara", email="80281999@holycross.edu.ph")); check(r.status_code == 200, "edit student via modal")
check(fetch_one("SELECT full_name FROM users WHERE username='80281999'")["full_name"] == "Mara Santos", "edit syncs account name")
r = ajax_post(c, f"/students/{sid}/edit", dict(base, email="80000000@holycross.edu.ph")); check(r.status_code == 422, "edit cannot move to another ID's email")
r = ajax_post(c, f"/students/{sid}/reset-password", {"method": "temp"}); check(r.status_code == 200 and r.get_json()["ok"], "student reset password (temp) works")
# legacy student (non 8-digit) is still editable with any valid email
leg = fetch_one("SELECT s.id, s.first_name, s.last_name, s.department_id, s.year_level, s.section, s.school_year_id FROM students s WHERE student_number='2026-0002'")
r = ajax_post(c, f"/students/{leg['id']}/edit", {"first_name": leg["first_name"], "last_name": leg["last_name"], "email": "legacy@gmail.com", "department_id": str(leg["department_id"]),
              "year_level": leg["year_level"], "section": leg["section"], "school_year_id": str(leg["school_year_id"])})
check(r.status_code == 200, "legacy student record still editable", r.get_json())
# school admin can manage students
c2 = app.test_client(); login(c2, "schooladmin", "SchoolAdmin@123")
check(ajax_get(c2, "/students/new").status_code == 200, "school admin can open Add Student")
check(ajax_get(c2, "/departments/new").status_code == 403, "school admin cannot open Add Department")
# departments
r = ajax_get(c, "/departments/new"); check(r.status_code == 200 and "Add Department" in r.get_data(as_text=True), "Add Department opens as a modal")
r = ajax_post(c, "/departments/new", {"name": "", "code": "x"}); check(r.status_code == 422 and {"name", "code"} <= set(r.get_json()["errors"]), "department field errors returned inline")
r = ajax_post(c, "/departments/new", {"name": "Graduate School", "code": "gs"}); check(r.status_code == 200, "department created (code upper-cased)")
check(fetch_one("SELECT code FROM departments WHERE name='Graduate School'")["code"] == "GS", "code stored upper-case")
did = fetch_one("SELECT id FROM departments WHERE code='GS'")["id"]
r = ajax_post(c, f"/departments/{did}/edit", {"name": "Graduate Studies", "code": "GS"}); check(r.status_code == 200, "edit department via modal")
# list pages render and contain refresh region
for u in ["/students", "/departments", "/super-admin/users"]:
    h = c.get(u).get_data(as_text=True); check('id="list-region"' in h and "data-modal-url" in h, f"{u} renders with modal triggers + list region")
raise SystemExit(summary())
