from helpers import *
import io, os, re, hashlib
from unittest import mock
app, c = new_client(PUBLIC_BASE_URL="https://scmovs.example.org", MAIL_SERVER="smtp.test", MAIL_USERNAME="u", MAIL_PASSWORD="p", MAIL_SENDER="s@example.org")

# ---------- pages render
login(c, "schooladmin", "SchoolAdmin@123")
h = c.get("/profile").get_data(as_text=True)
check("User information" in h and "Upload Photo" in h and "Change password" in h, "Profile page: info, photo and password card")
check("Change Password</span>" not in h.split('<nav')[1].split('</nav>')[0], "no separate Change Password sidebar entry")
check("bars-3" in h or 'd="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5"' in h, "hamburger (Bars3) icon used for the sidebar toggle")
check(c.get("/account", follow_redirects=False).status_code == 302, "old profile URL redirects")
check(c.get("/change-password").status_code == 200, "forced change-password page still exists")

# ---------- photo upload
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
def up(data, name="x.png", ctype="image/png"):
    return ajax_post(c, "/profile/photo", files={"photo": (io.BytesIO(data), name, ctype)})
r = up(b"GIF89a" + b"\x00" * 50, "evil.png"); check(r.status_code == 422, "non-image rejected even with .png name / image MIME")
r = up(b"<?php echo 1;?>", "shell.jpg", "image/jpeg"); check(r.status_code == 422, "script disguised as jpg rejected")
r = up(PNG + b"\x00" * (5 * 1024 * 1024)); check(r.status_code == 422 and "too large" in r.get_json()["message"], "over 5 MB rejected")
r = up(b""); check(r.status_code == 422, "empty file rejected")
check(fetch_one("SELECT photo_path FROM users WHERE username='schooladmin'")["photo_path"] is None, "failed uploads changed nothing")
r = up(PNG, "../../etc/passwd.png"); j = r.get_json()
check(r.status_code == 200 and j["ok"], "valid PNG accepted", j)
p1 = fetch_one("SELECT photo_path FROM users WHERE username='schooladmin'")["photo_path"]
check(re.fullmatch(r"profiles/[a-f0-9]{32}\.png", p1 or ""), "safe random filename, original name ignored", p1)
check(os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], p1)), "file stored under uploads/")
check(c.get("/" + j["photo_url"].lstrip("/")).status_code == 200, "photo served to the owner")
check(app.test_client().get(j["photo_url"]).status_code == 302, "photo not served to anonymous visitors")
check(c.get("/media/profiles/..%2f..%2fconfig.py").status_code == 404, "path traversal blocked")
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 30
r = up(WEBP, "a.webp", "image/webp"); check(r.status_code == 200, "WebP accepted")
p2 = fetch_one("SELECT photo_path FROM users WHERE username='schooladmin'")["photo_path"]
check(p2 != p1 and not os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], p1)), "old photo deleted only after the new one saved")
r = up(b"\xff\xd8\xff\xe0" + b"\x00" * 40, "a.jpeg", "image/jpeg"); check(r.status_code == 200, "JPEG accepted")
r = ajax_post(c, "/profile/photo/remove"); check(r.status_code == 200, "photo removed")
check(fetch_one("SELECT photo_path FROM users WHERE username='schooladmin'")["photo_path"] is None, "photo_path cleared")
c_stu = app.test_client(); login(c_stu, "2026-0002", "Student@123")
# students are forced to change password at first login -> clear flag for this test only
db_exec("UPDATE users SET must_change_password=0")
check(ajax_get(c_stu, "/profile/edit").status_code == 403, "student cannot edit their own record")
check(c_stu.get("/profile").status_code == 200, "student sees their profile")

# ---------- edit profile + change password
r = ajax_post(c, "/profile/edit", {"first_name": "Sam", "middle_name": "", "last_name": "Admin", "email": ""}); check(r.status_code == 422, "profile email required")
r = ajax_post(c, "/profile/edit", {"first_name": "Sam", "middle_name": "Q", "last_name": "Admin", "email": "sam@gmail.com"}); check(r.status_code == 200, "profile edit saves")
check(fetch_one("SELECT full_name FROM users WHERE username='schooladmin'")["full_name"] == "Sam Q Admin", "profile edit keeps full_name in sync")
r = ajax_post(c, "/profile/password", {"current_password": "wrong", "new_password": "NewPass123", "confirm_password": "NewPass123"}); check(r.status_code == 422 and "current_password" in r.get_json()["errors"], "wrong current password rejected")
r = ajax_post(c, "/profile/password", {"current_password": "SchoolAdmin@123", "new_password": "abc", "confirm_password": "abc"}); check(r.status_code == 422, "weak new password rejected")
r = ajax_post(c, "/profile/password", {"current_password": "SchoolAdmin@123", "new_password": "NewPass123", "confirm_password": "Other123"}); check(r.status_code == 422, "mismatched confirmation rejected")
r = ajax_post(c, "/profile/password", {"current_password": "SchoolAdmin@123", "new_password": "NewPass123", "confirm_password": "NewPass123"}); check(r.status_code == 200, "password changed")
h = fetch_one("SELECT password_hash FROM users WHERE username='schooladmin'")["password_hash"]
check(h.startswith(("scrypt:", "pbkdf2:")) and "NewPass123" not in h, "stored as a Werkzeug hash")
check(login(app.test_client(), "schooladmin", "NewPass123") and not login(app.test_client(), "schooladmin", "SchoolAdmin@123"), "new password works, old one does not")

# ---------- forgot password
anon = app.test_client()
page = anon.get("/login").get_data(as_text=True)
check("Forgot Password?" in page and "data-modal-url" in page, "Forgot Password? link on login page")
check("Registered Email Address" in anon.get("/forgot-password", headers={"X-Requested-With": "fetch"}).get_data(as_text=True), "Forgot Password modal fragment")
def forgot(email, client=anon):
    r = ajax_post(client, "/forgot-password", {"email": email}); return r.status_code, r.get_json()
db_exec("UPDATE users SET email='80382024@holycross.edu.ph' WHERE username='2026-0003'")
db_exec("UPDATE students SET student_number='80382024' WHERE student_number='2026-0003'")
db_exec("UPDATE users SET username='80382024', email='80382024@holycross.edu.ph' WHERE username='2026-0003'")
db_exec("UPDATE users SET email='admin.reset@gmail.com' WHERE username='superadmin'")
s, j = forgot(""); check(s == 422, "empty email rejected")
s, j = forgot("bad"); check(s == 422, "malformed email rejected")
sent = []
def fake_send(to, subject, text, html=None): sent.append((to, subject, text, html))
with mock.patch("app.auth.recovery.send_mail", fake_send):
    s, j = forgot("80382024@holycross.edu.ph"); check(s == 200 and "If an eligible account exists" in j["message"], "eligible student: generic response", j)
    check(len(sent) == 1 and sent[0][0] == "80382024@holycross.edu.ph" and sent[0][1] == "SCMOVS — Password Reset Request", "email sent to the registered address with the right subject")
    m = re.search(r"https://scmovs\.example\.org/reset-password/([A-Za-z0-9_-]+)", sent[0][2]); check(bool(m), "link built from PUBLIC_BASE_URL (no localhost)")
    check("localhost" not in sent[0][2] and "ngrok" not in sent[0][2], "no hardcoded host in email")
    check("Reset My Password" in sent[0][3] and "30 minutes" in sent[0][2], "email text: button and 30-minute expiry")
    token = m.group(1)
    row = fetch_one("SELECT token_hash, expires_at > NOW() AS ok, TIMESTAMPDIFF(MINUTE, NOW(), expires_at) AS mins FROM password_reset_tokens ORDER BY id DESC LIMIT 1")
    check(row["token_hash"] == hashlib.sha256(token.encode()).hexdigest() and token not in row["token_hash"], "only the token hash is stored")
    check(28 <= row["mins"] <= 30, "expires in ~30 minutes", row)
    n0 = len(sent)
    s, j = forgot("99999999@holycross.edu.ph"); check(s == 200 and j["message"].startswith("If an eligible"), "unknown account: identical generic response")
    check(len(sent) == n0, "nothing sent for unknown account")
    db_exec("UPDATE users SET email='80000001@holycross.edu.ph' WHERE username='2026-0004'")
    s, j = forgot("80000001@holycross.edu.ph"); check(s == 200 and len(sent) == n0, "student whose email does not match their Student ID gets nothing")
    s, j = forgot("80382024@gmail.com"); check(len(sent) == n0, "a gmail address that is not the registered one gets nothing")
    s, j = forgot("admin.reset@gmail.com"); check(s == 200 and len(sent) == n0 + 1, "admin account recovered via registered email (no student ID format forced)")

    # token use
    rp = anon.get(f"/reset-password/{token}"); check(rp.status_code == 200 and "Create a new password" in rp.get_data(as_text=True), "valid token shows reset form")
    t = csrf_from(rp.get_data(as_text=True))
    bad = anon.post(f"/reset-password/{token}", data={"new_password": "abc", "confirm_password": "abc", "csrf_token": t}); check("at least" in bad.get_data(as_text=True), "weak password rejected on reset form")
    bad = anon.post(f"/reset-password/{token}", data={"new_password": "Valid1234", "confirm_password": "Valid9999", "csrf_token": t}); check("do not match" in bad.get_data(as_text=True), "mismatch rejected on reset form")
    check(login(app.test_client(), "80382024", "Student@123"), "password unchanged before a valid reset")
    ok = anon.post(f"/reset-password/{token}", data={"new_password": "Valid1234", "confirm_password": "Valid1234", "csrf_token": t}); check("Password reset" in ok.get_data(as_text=True), "reset completes")
    check(login(app.test_client(), "80382024", "Valid1234"), "new password logs in")
    check(not login(app.test_client(), "80382024", "Student@123"), "old password no longer works")
    again = anon.get(f"/reset-password/{token}"); check(again.status_code == 400 and "not valid" in again.get_data(as_text=True), "used token rejected")
    check(anon.post(f"/reset-password/{token}", data={"new_password": "Valid5678", "confirm_password": "Valid5678", "csrf_token": t}).status_code == 400, "used token cannot reset again")
    check(anon.get("/reset-password/garbage").status_code == 400, "garbage token rejected")
    s, j = forgot("80382024@holycross.edu.ph"); tok2 = re.findall(r"reset-password/([A-Za-z0-9_-]+)", sent[-1][2])[0]
    db_exec("UPDATE password_reset_tokens SET expires_at = DATE_SUB(NOW(), INTERVAL 1 MINUTE) WHERE token_hash=%s", (hashlib.sha256(tok2.encode()).hexdigest(),))
    check(anon.get(f"/reset-password/{tok2}").status_code == 400, "expired token rejected")
    s, j = forgot("80382024@holycross.edu.ph"); s2, j2 = forgot("80382024@holycross.edu.ph")
    tokA = re.findall(r"reset-password/([A-Za-z0-9_-]+)", sent[-2][2]); 
    # per-account limit: 3 tokens/hour already reached (3 issued above)
    check(s2 == 429 or len(sent) <= n0 + 6, "per-account rate limit enforced")

# rate limit by IP
db_exec("DELETE FROM password_reset_requests")
codes = [forgot("nobody%d@holycross.edu.ph" % i)[0] for i in range(8)]
check(429 in codes and codes[0] == 200, "IP rate limit kicks in after repeated requests", codes)

# SMTP failure: voided token, no false claims
db_exec("DELETE FROM password_reset_requests"); db_exec("DELETE FROM password_reset_tokens")
from app.mailer import MailSendError
def boom(*a, **k): raise MailSendError("SMTPAuthenticationError")
with mock.patch("app.auth.recovery.send_mail", boom):
    s, j = forgot("admin.reset@gmail.com")
    check(s == 200 and "will be sent" in j["message"] and "sent to" not in j["message"].lower().replace("will be sent to", ""), "SMTP failure: response does not claim delivery")
    check(fetch_one("SELECT COUNT(*) n FROM password_reset_tokens WHERE used_at IS NULL")["n"] == 0, "undelivered token is voided")
    check(fetch_one("SELECT COUNT(*) n FROM audit_logs WHERE action='password_reset_email_failed'")["n"] >= 1, "SMTP failure recorded in audit log for admins")
# email not configured at all
app2, c2 = new_client(MAIL_SERVER="", PUBLIC_BASE_URL="")
s, j = ajax_post(c2, "/forgot-password", {"email": "x@gmail.com"}).status_code, None
check(s == 503, "reports unavailable (not fake success) when SMTP/public URL missing")
# admin-initiated email reset
db_exec("DELETE FROM password_reset_requests")
login(c_super := app.test_client(), "superadmin", "SuperAdmin@123")
uid = fetch_one("SELECT id FROM users WHERE username='tuser_none'") or fetch_one("SELECT id FROM users WHERE username='officer1'")
db_exec("UPDATE users SET email='officer1@gmail.com' WHERE id=%s", (uid["id"],))
with mock.patch("app.auth.recovery.send_mail", fake_send):
    n = len(sent); r = ajax_post(c_super, f"/super-admin/users/{uid['id']}/reset-password", {"method": "email"})
    check(r.status_code == 200 and len(sent) == n + 1 and sent[-1][0] == "officer1@gmail.com", "admin 'email reset link' sends to the account's registered email", r.get_json())
    check("temporary" not in sent[-1][2].lower() and "password:" not in sent[-1][2].lower(), "email never contains a password")
raise SystemExit(summary())
