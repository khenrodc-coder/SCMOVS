from helpers import *
import re
app, c = new_client(); db_exec("UPDATE users SET must_change_password=0")
login(c, "superadmin", "SuperAdmin@123")

def toggle_button(html, action_fragment):
    """Return the <button>...</button> of the form whose action contains action_fragment."""
    i = html.index(action_fragment); b = html.index("<button", i); return html[b:html.index("</button>", b)]

# ---- users: active -> check circle (green); deactivated -> X circle (red)
db_exec("UPDATE users SET is_active=0 WHERE username='schooladmin'")
uid_active = fetch_one("SELECT id FROM users WHERE username='officer1'")["id"]; uid_off = fetch_one("SELECT id FROM users WHERE username='schooladmin'")["id"]
h = c.get("/super-admin/users?status=").get_data(as_text=True) if False else c.get("/super-admin/users").get_data(as_text=True)
a = toggle_button(h, f"/users/{uid_active}/toggle-active"); i = toggle_button(h, f"/users/{uid_off}/toggle-active")
check("fa-circle-check" in a and "fa-circle-xmark" not in a and "text-green-700" in a, "users: active account shows a circle with a check (green)")
check("fa-circle-xmark" in i and "fa-circle-check" not in i and "text-red-700" in i, "users: deactivated account shows a circle with an X (red)")
check("Deactivate account" in a and "Activate account" in i, "users: tooltip/label still say what clicking does")
check("fa-ban" not in a + i, "users: old ban icon is gone")

# ---- departments
dep_off = fetch_one("SELECT id FROM departments WHERE code='EL'") or fetch_one("SELECT id FROM departments ORDER BY id LIMIT 1")
db_exec("UPDATE departments SET is_active=0 WHERE id=%s", (dep_off["id"],))
dep_on = fetch_one("SELECT id FROM departments WHERE is_active=1 LIMIT 1")
h = c.get("/departments").get_data(as_text=True)
check("fa-circle-check" in toggle_button(h, f"/departments/{dep_on['id']}/toggle-active"), "departments: active shows check circle")
check("fa-circle-xmark" in toggle_button(h, f"/departments/{dep_off['id']}/toggle-active"), "departments: deactivated shows X circle")

# ---- positions
pos_off = fetch_one("SELECT id FROM positions ORDER BY id LIMIT 1"); db_exec("UPDATE positions SET is_active=0 WHERE id=%s", (pos_off["id"],))
pos_on = fetch_one("SELECT id FROM positions WHERE is_active=1 LIMIT 1")
h = c.get("/positions").get_data(as_text=True)
check("fa-circle-check" in toggle_button(h, f"/positions/{pos_on['id']}/toggle-active"), "positions: active shows check circle")
check("fa-circle-xmark" in toggle_button(h, f"/positions/{pos_off['id']}/toggle-active"), "positions: deactivated shows X circle")

# ---- students: Deactivate button (student is active) = check circle; Activate button (student inactive) = X circle
sid_off = fetch_one("SELECT s.id FROM students s WHERE s.student_number='2026-0004'")["id"]; sid_on = fetch_one("SELECT s.id FROM students s WHERE s.student_number='2026-0005'")["id"]
db_exec("UPDATE students SET status='inactive' WHERE id=%s", (sid_off,))
h = c.get("/students?status=").get_data(as_text=True)
def student_btn(h, sid, status_value):
    i = h.index(f"/students/{sid}/status", h.index(f"/students/{sid}/edit") if f"/students/{sid}/edit" in h else 0)
    for m in re.finditer(rf'/students/{sid}/status.*?</form>', h, re.S):
        if f'name="status" value="{status_value}"' in m.group(0): return m.group(0)
    return ""
d = student_btn(h, sid_on, "inactive"); a = student_btn(h, sid_off, "active")
check("fa-circle-check" in d and "text-green-700" in d, "students: Deactivate button (active student) shows a check circle", d[-300:])
check("fa-circle-xmark" in a and "text-red-700" in a, "students: Activate button (inactive student) shows an X circle", a[-300:])

# ---- password eye markup: hidden state shows the closed eye, shown state shows the open eye
login_html = app.test_client().get("/login").get_data(as_text=True)
m = re.search(r'data-icon-show>(.*?)</span>\s*<span data-icon-hide class="hidden">(.*?)</span>', login_html, re.S)
SLASH = "M3.98 8.223"                      # a path segment that only the Heroicons eye-slash contains
check(m and SLASH in m.group(1) and SLASH not in m.group(2), "password toggle (login): closed eye is the one shown while the password is hidden")
modal_html = c.get("/profile").get_data(as_text=True)      # the Change Password card uses the same eye macro as the modals
mm = re.search(r'data-icon-show><i class="([^"]*)".*?data-icon-hide class="hidden"><i class="([^"]*)"', modal_html, re.S)
check(mm and "fa-eye-slash" in mm.group(1) and "fa-eye-slash" not in mm.group(2), "password toggle (Profile / modal macro): closed eye while hidden, open eye while shown")
raise SystemExit(summary())
