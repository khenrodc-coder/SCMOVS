from helpers import *  # noqa
import json

app, c = new_client()
if True:
    check(login(c, "superadmin", "SuperAdmin@123"), "super admin can log in")

    r = ajax_get(c, "/super-admin/users/new")
    html = r.get_data(as_text=True)
    check(r.status_code == 200 and 'data-modal-form' in html, "Add User returns a modal fragment")
    check("First name" in html and "Middle name" in html and "Last name" in html, "modal has First/Middle/Last name fields")
    check('name="email"' in html and re.search(r'name="email"[^>]*required', html) is not None, "email input has the required attribute")
    check("(optional)</span></label>\n    <input id=\"f_email\"" not in html, "email is not marked optional")
    check(ajax_get(c, "/super-admin/users/new").status_code == 200 and c.get("/super-admin/users/new").status_code == 302, "plain navigation to /users/new redirects to the list")

    base = {"username": "tuser1", "first_name": "Ana", "middle_name": "", "last_name": "Reyes", "email": "ana.reyes@gmail.com",
            "role": "school_admin", "password": "Passw0rd123", "confirm_password": "Passw0rd123"}
    def post(**over):
        d = dict(base); d.update(over)
        r = ajax_post(c, "/super-admin/users/new", d)
        return r.status_code, r.get_json()

    s, j = post(email="")
    check(s == 422 and "email" in j["errors"], "empty email rejected by the server", j)
    s, j = post(email="not-an-email")
    check(s == 422 and "email" in j["errors"], "malformed email rejected")
    s, j = post(first_name="")
    check(s == 422 and "first_name" in j["errors"], "first name required")
    s, j = post(last_name="")
    check(s == 422 and "last_name" in j["errors"], "last name required")
    s, j = post(first_name="Ana123")
    check(s == 422 and "first_name" in j["errors"], "digits in a name rejected")
    s, j = post(first_name="A" * 61)
    check(s == 422 and "first_name" in j["errors"], "over-long name rejected")
    s, j = post(role="super_admin")
    check(s == 422 and "role" in j["errors"], "Super Admin can NOT be created from Users (not offered, refused by the server)")
    s, j = post(role="student", email="")
    check(s == 422 and "student_number" in j["errors"], "Student role from Users requires the student fields")
    check("name=\"password\"" not in html and "name=\"confirm_password\"" not in html, "Add User no longer asks for a password (it is generated and emailed)")
    check("emailed to the address above" in html, "the form explains that the initial password is emailed")
    check(fetch_one("SELECT id FROM users WHERE username='tuser1'") is None, "nothing was saved by any invalid request")

    s, j = post(first_name="  Ana   Liza ", middle_name=" Cruz ", email="  ANA.Reyes@Gmail.COM ")
    check(s == 200 and j["ok"], "valid user created", j)
    row = fetch_one("SELECT first_name, middle_name, last_name, full_name, email FROM users WHERE username='tuser1'")
    check(row and row["first_name"] == "Ana Liza" and row["middle_name"] == "Cruz" and row["last_name"] == "Reyes", "name parts saved trimmed", row)
    check(row and row["full_name"] == "Ana Liza Cruz Reyes", "full_name kept in sync for the rest of the system", row)
    check(row and row["email"] == "ana.reyes@gmail.com", "email normalised to lowercase", row)
    s, j = post(username="tuser2", email="ANA.reyes@gmail.com")
    check(s == 422 and "email" in j["errors"], "duplicate email rejected case-insensitively")
    s, j = post(email="x@y.com")
    check(s == 422 and "username" in j["errors"], "duplicate username rejected")

    uid = fetch_one("SELECT id FROM users WHERE username='tuser1'")["id"]
    r = ajax_get(c, f"/super-admin/users/{uid}/edit"); h = r.get_data(as_text=True)
    check(r.status_code == 200 and 'value="Ana Liza"' in h and 'value="Cruz"' in h, "Edit modal is pre-filled with the three names")
    r = ajax_post(c, f"/super-admin/users/{uid}/edit", {"first_name": "Ana", "middle_name": "", "last_name": "Reyes", "email": "", "role": "school_admin"})
    check(r.status_code == 422 and "email" in r.get_json()["errors"], "edit cannot blank the email")
    r = ajax_post(c, f"/super-admin/users/{uid}/edit", {"first_name": "Anna", "middle_name": "", "last_name": "Reyes", "email": "anna@gmail.com", "role": "school_admin"})
    check(r.status_code == 200, "edit saves")
    check(fetch_one("SELECT full_name FROM users WHERE id=%s", (uid,))["full_name"] == "Anna Reyes", "edit keeps full_name in sync")

    # student-linked account: email must match the Student ID rule when the number is 8 digits
    db_exec("UPDATE students SET student_number='80382024' WHERE student_number='2026-0001'")
    db_exec("UPDATE users SET username='80382024' WHERE username='2026-0001'")
    suid = fetch_one("SELECT id FROM users WHERE username='80382024'")["id"]
    r = ajax_post(c, f"/super-admin/users/{suid}/edit", {"first_name": "A", "last_name": "B", "email": "80382024@yahoo.com", "role": "student"})
    check(r.status_code == 422 and "accepted" in r.get_json()["errors"]["email"], "student email must be @holycross.edu.ph or @gmail.com")
    r = ajax_post(c, f"/super-admin/users/{suid}/edit", {"first_name": "A", "last_name": "B", "email": "80281999@holycross.edu.ph", "role": "student"})
    check(r.status_code == 422 and "does not match" in r.get_json()["errors"]["email"], "student email number must match Student ID", r.get_json())
    r = ajax_post(c, f"/super-admin/users/{suid}/edit", {"first_name": "Al", "last_name": "Bo", "email": "80382024@holycross.edu.ph", "role": "student"})
    check(r.status_code == 200, "matching student email accepted", r.get_json())
    check(fetch_one("SELECT first_name FROM students WHERE student_number='80382024'")["first_name"] == "Al", "student record name stays in sync")

    # permissions
    c2 = app.test_client(); 
    check(login(c2, "schooladmin", "SchoolAdmin@123"), "school admin logs in")
    check(ajax_get(c2, "/super-admin/users/new").status_code == 403, "school admin cannot open Add User")
    check(ajax_post(c2, "/super-admin/users/new", base).status_code == 403, "school admin cannot create users")
    c3 = app.test_client()
    check(c3.get("/super-admin/users/new").status_code == 302, "anonymous is redirected to login")
    r = c3.post("/super-admin/users/new", data=base)
    check(r.status_code in (302, 400), "anonymous POST without CSRF is refused", r.status_code)
    r = c.post("/super-admin/users/new", data=base, headers={"X-Requested-With": "fetch"})
    check(r.status_code == 400, "logged-in POST without a CSRF token is refused", r.status_code)

    # reset password modal
    r = ajax_get(c, f"/super-admin/users/{uid}/reset-password"); h = r.get_data(as_text=True)
    check(r.status_code == 200 and "Reset Password" in h and 'value="temp"' in h, "Reset Password opens a modal")
    check('value="email"' in h and "disabled" in h.split('value="email"')[1][:80], "email option disabled while SMTP is not configured")
    r = ajax_post(c, f"/super-admin/users/{uid}/reset-password", {"method": "email"})
    check(r.status_code == 422, "email reset refused when SMTP is unavailable", r.get_json())
    r = ajax_post(c, f"/super-admin/users/{uid}/reset-password", {"method": "temp"})
    j = r.get_json()
    check(r.status_code == 200 and j["ok"] and "temp-pw" in j["html_result"], "temporary password issued once in the modal")
    check("no-store" in r.headers.get("Cache-Control", ""), "temporary password response is not cacheable")
    pw = re.search(r'value="([A-Za-z0-9]{12,})"', j["html_result"]).group(1)
    check(login(app.test_client(), "tuser1", pw), "the temporary password works for login")
    own = fetch_one("SELECT id FROM users WHERE username='superadmin'")["id"]
    r = ajax_post(c, f"/super-admin/users/{own}/reset-password", {"method": "temp"})
    check(r.status_code == 422, "cannot reset your own password from User Management")

raise SystemExit(summary())
