from helpers import *
from unittest import mock
app, c = new_client(PUBLIC_BASE_URL="https://scmovs.example.org", MAIL_SERVER="smtp.test", MAIL_USERNAME="u", MAIL_PASSWORD="p", MAIL_SENDER="s@x.org")
db_exec("UPDATE users SET must_change_password=0")
login(c, "superadmin", "SuperAdmin@123")
_sent_welcome = []
mock.patch("app.accounts.send_mail", lambda *a, **k: _sent_welcome.append(a)).start()      # never send real email from tests
dep = fetch_one("SELECT id FROM departments WHERE code='COL'")["id"]; yr = fetch_one("SELECT id FROM school_years WHERE status='active'")["id"]

# ---------- staff accounts (Users page)
base = {"username": "u0", "first_name": "Ana", "middle_name": "", "last_name": "Reyes", "email": "", "role": "school_admin", "password": "Passw0rd123", "confirm_password": "Passw0rd123"}
def staff(n, email):
    r = ajax_post(c, "/super-admin/users/new", dict(base, username=f"stf{n}", email=email)); return r.status_code, r.get_json()
for n, (email, should) in enumerate([("staffone@gmail.com", True), ("KhenRodC2@GMAIL.com", True), ("registrar@holycross.edu.ph", True),
        ("someone@yahoo.com", False), ("someone@outlook.com", False), ("someone@3holycross.edu.ph", False), ("someone@gmail.com.ph", False),
        ("someone@mail.gmail.com", False), ("someone@holycross.edu", False), ("someone@HOLYCROSS.EDU.PH.evil.com", False)]):
    s, j = staff(n, email)
    ok = (s == 200) if should else (s == 422 and "Only @gmail.com and @holycross.edu.ph" in j["errors"].get("email", ""))
    check(ok, f"staff {email!r}: {'accepted' if should else 'rejected with the two-domain message'}", j)
check(fetch_one("SELECT email FROM users WHERE username='stf1'")["email"] == "khenrodc2@gmail.com", "email stored lower-cased")
check(fetch_one("SELECT COUNT(*) n FROM users WHERE username IN ('stf3','stf4','stf5','stf6','stf7','stf8','stf9')")["n"] == 0, "no account was created for any rejected domain")

# ---------- profile edit
cs = app.test_client(); login(cs, "schooladmin", "SchoolAdmin@123")
p = {"first_name": "Sam", "middle_name": "", "last_name": "Admin"}
check(ajax_post(cs, "/profile/edit", dict(p, email="sam@yahoo.com")).status_code == 422, "profile: yahoo rejected")
check(ajax_post(cs, "/profile/edit", dict(p, email="sam@gmail.com")).status_code == 200, "profile: gmail accepted")
check(ajax_post(cs, "/profile/edit", dict(p, email="sam@holycross.edu.ph")).status_code == 200, "profile: holycross accepted")

# ---------- students: school address (must match ID) OR any personal gmail
sbase = {"student_number": "80000001", "first_name": "Khen", "middle_name": "", "last_name": "Rod", "email": "", "department_id": str(dep),
         "year_level": "1st Year", "section": "A", "school_year_id": str(yr)}
def stu(num, email):
    r = ajax_post(c, "/students/new", dict(sbase, student_number=num, email=email)); return r.status_code, r.get_json()
s, j = stu("80000001", "khenrodc@gmail.com"); check(s == 200, "student with personal khenrodc@gmail.com accepted", j)
s, j = stu("80000002", "80000002@holycross.edu.ph"); check(s == 200, "student with own school address accepted", j)
s, j = stu("80000003", "80000009@holycross.edu.ph"); check(s == 422 and "does not match" in j["errors"]["email"], "school address with ANOTHER student's number rejected")
s, j = stu("80000003", "juan@holycross.edu.ph"); check(s == 422 and "8 digits" in j["errors"]["email"], "school address without the 8-digit number rejected")
s, j = stu("80000003", "80000003@yahoo.com"); check(s == 422 and "accepted" in j["errors"]["email"], "student yahoo rejected")
s, j = stu("80000003", "80000003@3holycross.edu.ph"); check(s == 422, "old @3holycross.edu.ph rejected")
check(fetch_one("SELECT COUNT(*) n FROM students WHERE student_number='80000003'")["n"] == 0, "rejected students were not saved")
s, j = stu("80000004", "khenrodc@gmail.com"); check(s == 422 and "already in use" in j["errors"]["email"], "the same gmail cannot be used by two accounts")

# ---------- forgot password
anon = app.test_client(); sent = []
def fake(to, subject, text, html=None): sent.append(to)
def forgot(email): r = ajax_post(anon, "/forgot-password", {"email": email}); return r.status_code, r.get_json()
db_exec("DELETE FROM password_reset_requests")
with mock.patch("app.auth.recovery.send_mail", fake):
    s, j = forgot("khenrodc@gmail.com"); check(s == 200 and sent == ["khenrodc@gmail.com"], "student registered with gmail gets the reset email at that gmail", (s, sent))
    s, j = forgot("80000002@holycross.edu.ph"); check(s == 200 and sent[-1] == "80000002@holycross.edu.ph", "student registered with school address gets it there")
    s, j = forgot("khenrodc2@gmail.com"); check(s == 200 and sent[-1] == "khenrodc2@gmail.com", "admin registered with gmail gets the reset email")
    n = len(sent)
    s, j = forgot("someone@yahoo.com"); check(s == 422 and "Only @gmail.com and @holycross.edu.ph" in j["message"] and len(sent) == n, "other domains are refused at the form and nothing is sent")
    s, j = forgot("nobody@gmail.com"); check(s == 200 and j["message"].startswith("If an eligible") and len(sent) == n, "unknown gmail: same generic answer, nothing sent")
# a student whose school address carries someone else's number is still not eligible
db_exec("UPDATE users SET email='80000009@holycross.edu.ph' WHERE username='80000002'")
with mock.patch("app.auth.recovery.send_mail", fake):
    n = len(sent); db_exec("DELETE FROM password_reset_requests"); forgot("80000009@holycross.edu.ph"); check(len(sent) == n, "school address not matching the Student ID is not eligible for recovery")
raise SystemExit(summary())
