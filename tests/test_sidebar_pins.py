from helpers import *
import re
app, c0 = new_client()
db_exec("UPDATE users SET must_change_password=0")
users = {"super_admin": ("superadmin", "SuperAdmin@123", "/super-admin/dashboard"), "school_admin": ("schooladmin", "SchoolAdmin@123", "/school-admin/dashboard"),
         "council_officer": ("officer1", "Officer@123", "/council-officer/dashboard"), "student": ("2026-0002", "Student@123", "/dashboard")}
expect = {"super_admin": {"Dashboard", "Users", "Students", "Elections", "Reports", "Settings", "Profile"},
          "school_admin": {"Dashboard", "Students", "Elections", "Candidates", "Reports", "Profile"},
          "council_officer": {"My Elections", "Dashboard", "Events", "Budgets", "Reports", "Profile"},
          "student": {"My Elections", "Dashboard", "Profile"}}
for role, (u, pw, home) in users.items():
    cl = app.test_client(); login(cl, u, pw)
    h = cl.get(home, follow_redirects=True).get_data(as_text=True)
    nav = h.split("<nav")[1].split("</nav>")[0]
    links = re.findall(r'<a href="[^"]*" title="([^"]*)"[^>]*class="nav-item[^>]*>', nav)
    tags = re.findall(r'<a href="[^"]*" title="([^"]*)"([^>]*)class="nav-item', nav)
    pinned = {t for t, attrs in tags if "data-pin" in attrs}
    check(set(links) >= pinned and pinned <= expect[role] and pinned, f"{role}: pinned links are a subset of the allowed key links: {sorted(pinned)}")
    check(len(pinned) < len(links) or role == "student", f"{role}: collapsed shows fewer icons ({len(pinned)}) than expanded ({len(links)})")
    check(pinned == (expect[role] & set(links)), f"{role}: every key link the role can see is pinned", (pinned, expect[role] & set(links)))
    check("Dashboard" in pinned and "Profile" in pinned, f"{role}: Dashboard and Profile always stay visible")
    check(len(links) == len(tags), f"{role}: all links still exist in the expanded sidebar")
l = c0.get("/login").get_data(as_text=True)
css = app.test_client(); login(css, "superadmin", "SuperAdmin@123"); h = css.get("/super-admin/dashboard").get_data(as_text=True)
check("html.sb-collapsed #sidebar .nav-item:not([data-pin]) { display: none; }" in h, "collapsed CSS hides unpinned links")
check(":not(:has(.nav-item[data-pin]))" in h, "collapsed CSS hides groups with no pinned link")
m = re.search(r"@media \(min-width: 768px\) \{(.*?)\n    \}", h, re.S)
check(m and "data-pin" in m.group(1), "the rule is desktop-only (mobile menu still shows everything)")
raise SystemExit(summary())
