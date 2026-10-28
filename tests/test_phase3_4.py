from helpers import *
import re
app, c = new_client()
login(c, "superadmin", "SuperAdmin@123")

# ---------- Super Admin dashboard
h = c.get("/super-admin/dashboard").get_data(as_text=True)
check(c.get("/super-admin/dashboard").status_code == 200, "Super Admin dashboard renders")
for label in ["Total students", "Voting participation", "Council officers", "Active departments"]:
    check(label not in h, f"card removed: {label}")
for label in ["Total users", "Active elections", "Pending candidates", "Approved budgets"]:
    check(label in h, f"other cards kept: {label}")
check("charts_common.js" in h and "max-w-[1400px]" in h, "dashboard uses shared charts + width cap")
from app.admin.services import get_dashboard_stats
with app.app_context():
    d = get_dashboard_stats()
check("total_students" in d["stats"] and "department_stats" in d and d["charts"]["budget_trend"]["labels"], "underlying stats still available; new dashboard data present")
js = open("static/js/super_admin_dashboard.js").read()
check('line("chart-budget-trend"' in js and 'vbar("chart-open-participation"' in js, "dashboard script draws the budget line chart and the open-election bar chart")
cc = open("static/js/charts_common.js").read()
check('indexAxis: "y"' in cc and 'type: "pie"' in cc and 'type: "line"' in cc, "Chart.js helpers: horizontal bar, pie and line")
check("%" in cc and "generateLabels" in cc, "pie shows counts and percentages in legend + tooltip")

# ---------- School admin dashboard
cs = app.test_client(); login(cs, "schooladmin", "SchoolAdmin@123"); db_exec("UPDATE users SET must_change_password=0")
h = cs.get("/school-admin/dashboard").get_data(as_text=True)
check("chart-sa-departments" in h and "chart-sa-candidates" in h, "School Admin dashboard has new charts")
m = re.search(r'id="sa-chart-data" type="application/json">(.*?)</script>', h, re.S)
import json; data = json.loads(m.group(1))
real = fetch_one("SELECT COUNT(*) n FROM students WHERE status<>'archived'")["n"]
check(sum(data["departments"]["values"]) == real, "chart numbers equal the database counts", (data["departments"], real))
check("ballot" not in m.group(1).lower() and "vote" not in m.group(1).lower(), "chart data carries no ballot/vote information")
# officer dashboard
co = app.test_client(); db_exec("UPDATE users SET must_change_password=0"); login(co, "officer1", "Officer@123")
r = co.get("/council-officer/dashboard"); check(r.status_code == 200 and "charts_common.js" in r.get_data(as_text=True), "Council Officer dashboard renders with shared charts")
check("Super Admin" not in re.sub(r"<[^>]+>", "", re.sub(r"(?s)<script.*?</script>", "", co.get("/council-officer/dashboard").get_data(as_text=True).split("<main")[1])), "officer dashboard exposes no Super Admin controls")

# ---------- Settings
r = c.get("/settings"); h = r.get_data(as_text=True)
check(r.status_code == 200, "Settings renders")
check(all(f'id="{k}"' in h for k in ["general", "academic", "election", "notification", "security"]), "all five setting groups still present")
check(h.index('id="academic"') < h.index('id="general"') or "lg:order-2" in h, "Academic/Election/Notifications are placed in the upper-right column")
fields = ["system_name", "school_name", "school_address", "election_require_candidate_per_position", "election_block_pending_candidates",
          "notifications_enabled", "session_timeout_minutes", "password_min_length", "max_failed_logins", "lockout_minutes"]
check(all(f'name="{f}"' in h for f in fields), "every existing setting field is still on the page")
tok = csrf_from(h)
r = c.post("/settings/security", data={"csrf_token": tok, "session_timeout_minutes": "45", "password_min_length": "8", "max_failed_logins": "5", "lockout_minutes": "15"})
check(r.status_code == 302 and fetch_one("SELECT setting_value v FROM system_settings WHERE setting_key='session_timeout_minutes'")["v"] == "45", "saving a settings group still works")
check(cs.get("/settings").status_code == 403, "school admin still cannot open Settings")

# ---------- Notifications
uid = fetch_one("SELECT id FROM users WHERE username='superadmin'")["id"]
other = fetch_one("SELECT id FROM users WHERE username='schooladmin'")["id"]
db_exec("DELETE FROM notifications")
db_exec("INSERT INTO notifications (user_id,title,message,related_module,link_url) VALUES (%s,'Voting opened: X','Voting for X has opened.','elections','/elections')", (uid,))
db_exec("INSERT INTO notifications (user_id,title,message,related_module,link_url) VALUES (%s,'Old one','Read already','elections','//evil.example/x')", (uid,))
db_exec("UPDATE notifications SET is_read=1 WHERE title='Old one'")
db_exec("INSERT INTO notifications (user_id,title,message,related_module) VALUES (%s,'Private to admin','secret','elections')", (other,))
j = c.get("/notifications/api").get_json()
check(j["ok"] and j["unread"] == 1 and len(j["items"]) == 2, "API returns only my notifications with the unread count", j)
check(all(i["title"] != "Private to admin" for i in j["items"]), "other users' notifications are never returned")
item = [i for i in j["items"] if i["title"].startswith("Voting")][0]
check({"id", "title", "message", "created_at", "is_read", "url"} <= set(item) and item["url"] == "/elections", "item has title, message, time, read state, link")
check([i for i in j["items"] if i["title"] == "Old one"][0]["url"] is None, "unsafe external link is dropped")
check(app.test_client().get("/notifications/api").status_code == 302, "API requires login")
oid = fetch_one("SELECT id FROM notifications WHERE user_id=%s", (other,))["id"]
r = ajax_post(c, f"/notifications/api/{oid}/read"); check(r.status_code == 404, "cannot mark someone else's notification")
check(fetch_one("SELECT is_read FROM notifications WHERE id=%s", (oid,))["is_read"] == 0, "other user's notification unchanged")
r = c.post(f"/notifications/api/{item['id']}/read", headers={"X-Requested-With": "fetch"}); check(r.status_code == 400, "mark-read needs CSRF token")
r = ajax_post(c, f"/notifications/api/{item['id']}/read"); check(r.status_code == 200 and r.get_json()["unread"] == 0, "Mark as read saves and returns new unread count")
check(fetch_one("SELECT is_read, read_at FROM notifications WHERE id=%s", (item["id"],))["read_at"] is not None, "read status stored in MySQL")
db_exec("UPDATE notifications SET is_read=0 WHERE user_id=%s", (uid,))
r = ajax_post(c, "/notifications/api/read-all"); check(r.get_json()["unread"] == 0, "Mark all as read works")
check(fetch_one("SELECT is_read FROM notifications WHERE id=%s", (oid,))["is_read"] == 0, "Mark all only touches my own rows")
page = c.get("/super-admin/dashboard").get_data(as_text=True)
check('id="notif-btn"' in page and 'id="notif-readall"' in page and "Loading" in page and "all caught up" in page, "bell panel markup: loading, empty state, mark-all")

# election open/close creates a deduplicated admin notification
from app.elections import services as es
with app.app_context():
    from app.db import get_db
    cur = get_db().cursor(); election = {"id": 1, "name": "Test", "department_id": 3, "school_year_id": 1}
    from flask import url_for
    with app.test_request_context():
        for _ in range(2):
            es._notify_admins(cur, election, "Voting opened: Test", "Voting for 'Test' has opened.", "/elections/1")
    get_db().commit(); cur.close()
check(fetch_one("SELECT COUNT(*) n FROM notifications WHERE title='Voting opened: Test' AND user_id=%s", (uid,))["n"] == 1, "duplicate admin notification prevented")
check(fetch_one("SELECT COUNT(*) n FROM notifications WHERE title='Voting opened: Test' AND user_id=%s", (other,))["n"] == 1, "School Admin also notified")

# ---------- Dark mode
check('id="theme-toggle"' in page and "dark.css" in page, "Super Admin sees the theme toggle")
check('<html lang="en">' in page, "light is the default theme")
r = ajax_post(c, "/profile/theme", {"theme": "dark"}); check(r.status_code == 200, "dark mode saved")
check(fetch_one("SELECT theme_preference t FROM users WHERE id=%s", (uid,))["t"] == "dark", "preference persisted in MySQL")
for u in ["/super-admin/dashboard", "/settings", "/super-admin/users"]:
    check('<html lang="en" class="dark">' in c.get(u).get_data(as_text=True), f"dark class rendered server-side on {u} (no flash)")
check(ajax_post(c, "/profile/theme", {"theme": "purple"}).status_code == 422, "invalid theme rejected")
for name, cl in [("schooladmin", cs), ("officer1", co)]:
    r = ajax_post(cl, "/profile/theme", {"theme": "dark"}); check(r.status_code == 403, f"{name} cannot set dark mode (server enforced)")
    check('class="dark"' not in cl.get("/dashboard", follow_redirects=True).get_data(as_text=True)[:200], f"{name} never gets the dark class")
    check('id="theme-toggle"' not in cl.get("/dashboard", follow_redirects=True).get_data(as_text=True), f"{name} has no theme toggle")
db_exec("UPDATE users SET theme_preference='dark' WHERE username='schooladmin'")
check('class="dark"' not in cs.get("/school-admin/dashboard").get_data(as_text=True)[:200], "even a tampered preference does not darken a School Admin page")
css = open("static/css/dark.css").read()
check(all(sel in css for sel in ["html.dark .bg-white", "html.dark input", ".scmovs-modal-dialog", "#notif-panel", "[data-icon-select]", "html.dark thead"]), "dark CSS covers cards, forms, tables, modals, dropdowns, notification panel")
ajax_post(c, "/profile/theme", {"theme": "light"})

# ---------- Sidebar
l = c.get("/super-admin/dashboard").get_data(as_text=True)
check("html.sb-collapsed #sidebar .brand { display: none; }" in l, "collapsed sidebar hides the logo and branding completely")
check("brand-row" in l and 'id="sidebar-collapse"' in l and "M3.75 6.75h16.5M3.75 12h16.5" in l, "toggle uses the three-line Bars3 icon and stays in the header row")
check("sb-collapsed #sidebar .brand-row { justify-content: center" in l, "toggle stays centred and visible when collapsed")
check("brand-text" in l and "Holy Cross College seal" in l, "logo present when expanded")
for who, cl in [("super", c), ("school", cs), ("officer", co), ("student", None)]:
    if cl is None:
        cl = app.test_client(); login(cl, "2026-0002", "Student@123")
        db_exec("UPDATE users SET must_change_password=0"); login(cl, "2026-0002", "Student@123")
    pg = cl.get("/dashboard", follow_redirects=True).get_data(as_text=True)
    check('id="sidebar-collapse"' in pg and 'id="sidebar-toggle"' in pg, f"hamburger toggles present for {who}")
nav = l.split("<nav")[1].split("</nav>")[0]
check(nav.count(">Profile<") == 1 and "Change Password" not in nav and "Account" not in re.sub(r"<[^>]+>", " ", nav), "sidebar has one 'Profile' entry, no Change Password / Account group")
raise SystemExit(summary())
