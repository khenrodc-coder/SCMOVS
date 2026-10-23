from helpers import *
import re
from unittest import mock
from werkzeug.security import check_password_hash
from app.mailer import MailSendError
app, c = new_client(PUBLIC_BASE_URL="https://scmovs.example.org", MAIL_SERVER="smtp.test", MAIL_USERNAME="u", MAIL_PASSWORD="p", MAIL_SENDER="s@x.org")
db_exec("UPDATE users SET must_change_password=0")
login(c, "superadmin", "SuperAdmin@123")
dep = fetch_one("SELECT id FROM departments WHERE code='COL'")["id"]; yr = fetch_one("SELECT id FROM school_years WHERE status='active'")["id"]
sent = []
def fake(to, subject, text, html=None): sent.append({"to": to, "subject": subject, "text": text, "html": html})
def boom(*a, **k): raise MailSendError("SMTPAuthenticationError")
staff = {"username": "newstaff", "first_name": "Ana", "middle_name": "", "last_name": "Reyes", "email": "khenrodc@gmail.com", "role": "school_admin"}
student = {"role": "student", "student_number": "80777001", "first_name": "Khen", "middle_name": "", "last_name": "Rod", "email": "khenstudent@gmail.com",
           "department_id": str(dep), "year_level": "1st Year", "section": "A", "school_year_id": str(yr)}
def post(url, data): r = ajax_post(c, url, data); return r.status_code, r.get_json(), r

# ---------- 1) staff account: password generated and emailed, never shown
with mock.patch("app.accounts.send_mail", fake):
    s, j, r = post("/super-admin/users/new", staff)
check(s == 200 and j["ok"] and "html_result" not in j, "staff created; no password shown on screen when the email goes out", j)
check("emailed to kh***@gmail.com" in j["message"], "the message says where it was sent (address masked)", j["message"])
check(len(sent) == 1 and sent[0]["to"] == "khenrodc@gmail.com", "email sent to the new user's own address", sent[:1] and sent[0]["to"])
mail = sent[0]; pw = re.search(r"Initial password: (\S+)", mail["text"]).group(1)
check(mail["subject"] == "SCMOVS \u2014 Your Account Has Been Created", "subject line")
check("Username: newstaff" in mail["text"] and "https://scmovs.example.org/login" in mail["text"], "email has the username and the login link built from PUBLIC_BASE_URL")
check(pw in mail["html"] and "Sign in" in mail["html"], "HTML version has the password and a sign-in button")
check(len(pw) >= 12 and re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw), "password is random, 12+ characters, letters and numbers", pw)
check("localhost" not in mail["text"] and "ngrok" not in mail["text"], "no hardcoded host in the email")
row = fetch_one("SELECT password_hash, must_change_password FROM users WHERE username='newstaff'")
check(row["password_hash"] != pw and check_password_hash(row["password_hash"], pw), "only the hash is stored, and it matches the emailed password")
check(row["must_change_password"] == 1, "the user must change the password at first login")
check(login(app.test_client(), "newstaff", pw), "the emailed password logs in")
cl = app.test_client(); login(cl, "newstaff", pw); r = cl.get("/school-admin/dashboard"); check(r.status_code == 302 and "change-password" in r.headers["Location"], "first login is forced to the change-password page")
log = fetch_one("SELECT description FROM audit_logs WHERE action='initial_password_emailed' ORDER BY id DESC LIMIT 1")
check(log and pw not in log["description"] and "kh***@gmail.com" in log["description"], "audit log records that it was emailed, never the password", log)
check(all(pw not in (x["description"] or "") for x in fetch_all("SELECT description FROM audit_logs")), "the password appears nowhere in the audit log")
check(all(pw not in (x["message"] or "") for x in fetch_all("SELECT message FROM notifications")), "nor in any notification")

# ---------- 2) student account from the Users form
sent.clear()
with mock.patch("app.accounts.send_mail", fake):
    s, j, r = post("/super-admin/users/new", student)
check(s == 200 and j["ok"] and "html_result" not in j and sent and sent[0]["to"] == "khenstudent@gmail.com", "student created from Add User: password emailed to their Gmail", j)
pw2 = re.search(r"Initial password: (\S+)", sent[0]["text"]).group(1)
check("Username: 80777001" in sent[0]["text"] and login(app.test_client(), "80777001", pw2), "student logs in with Student ID + the emailed password")

# ---------- 3) student from the Students page
sent.clear(); sb = dict(student, student_number="80777002", email="80777002@holycross.edu.ph", role=None); sb.pop("role")
with mock.patch("app.accounts.send_mail", fake):
    s, j, r = post("/students/new", sb)
check(s == 200 and j["ok"] and "html_result" not in j and sent and sent[0]["to"] == "80777002@holycross.edu.ph", "Students page: password emailed to the school address as well", j)
check(login(app.test_client(), "80777002", re.search(r"Initial password: (\S+)", sent[0]["text"]).group(1)), "and it works")

# ---------- 4) nothing is sent when the form is invalid
sent.clear()
with mock.patch("app.accounts.send_mail", fake):
    post("/super-admin/users/new", dict(staff, username="bad1", email="x@yahoo.com"))
    post("/super-admin/users/new", dict(staff, username="bad2", first_name=""))
    post("/super-admin/users/new", dict(staff, username="newstaff", email="other@gmail.com"))      # duplicate username
    post("/students/new", dict(sb, student_number="1234"))
check(sent == [], "no email goes out for rejected submissions")
check(fetch_one("SELECT COUNT(*) n FROM users WHERE username IN ('bad1','bad2')")["n"] == 0, "and no account is created")

# ---------- 5) email cannot be sent: account exists, password shown ONCE to the admin with a clear warning
with mock.patch("app.accounts.send_mail", boom):
    s, j, r = post("/super-admin/users/new", dict(staff, username="nomail1", email="nomail1@gmail.com"))
check(s == 200 and j["ok"] and "not sent" in j["message"] and "html_result" in j, "SMTP failure: account still created, admin is told the email was not sent", j)
shown = re.search(r'id="temp-pw"[^>]*value="([^"]+)"', j["html_result"]).group(1)
check("could not be emailed" in j["html_result"] and "nomail1@gmail.com" in j["html_result"], "the warning names the address and says why")
check("no-store" in r.headers.get("Cache-Control", ""), "that response is not cacheable")
check(login(app.test_client(), "nomail1", shown), "the shown password works, so the user is never locked out")
check(fetch_one("SELECT COUNT(*) n FROM audit_logs WHERE action='initial_password_email_failed'")["n"] >= 1, "failure is recorded in the audit log")
check(all(shown not in (x["description"] or "") for x in fetch_all("SELECT description FROM audit_logs")), "even then the password is not in the audit log")

# ---------- 6) email not configured at all
app2, c2 = new_client(MAIL_SERVER="", PUBLIC_BASE_URL="")
login(c2, "superadmin", "SuperAdmin@123"); db_exec("UPDATE users SET must_change_password=0")
r = ajax_post(c2, "/super-admin/users/new", dict(staff, username="nomail2", email="nomail2@gmail.com")); j = r.get_json()
check(r.status_code == 200 and "not configured" in j["html_result"] and "temp-pw" in j["html_result"], "SMTP not configured: account created, password shown once with the reason", j.get("message"))

# ---------- 7) the other password flows are untouched
with mock.patch("app.accounts.send_mail", fake):
    h = ajax_get(c, "/super-admin/users/new").get_data(as_text=True)
check('data-value="school_admin"' in h and 'name="password"' not in h, "Add User form still works without the password fields")
uid = fetch_one("SELECT id FROM users WHERE username='newstaff'")["id"]
r = ajax_post(c, f"/super-admin/users/{uid}/reset-password", {"method": "temp"}); check(r.status_code == 200 and "temp-pw" in r.get_json()["html_result"], "admin 'temporary password' reset still works")
raise SystemExit(summary())
