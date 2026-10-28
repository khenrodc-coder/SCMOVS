from helpers import *
import re, json, html as _html
app, c = new_client(); db_exec("UPDATE users SET must_change_password=0")
login(c, "superadmin", "SuperAdmin@123")
from app.admin.services import get_dashboard_stats
from app.validators import display_name
page = c.get("/super-admin/dashboard").get_data(as_text=True)

# ---- the four cards are gone, four remain; Department Statistics replaces them
check("Total users" in page and "Active elections" in page and "Pending candidates" in page and "Approved budgets" in page, "the four remaining cards are there")
stats_html = page.split('aria-label="Statistics"')[1].split("</section>")[0]
check(not any(t in stats_html for t in ["Projects", "Events", "Approved expenses", "Available balance"]), "Projects, Events, Approved Expenses and Available Balance cards are removed")
check("Department Statistics" in page and "Eligible Voters" in page and "Votes Cast" in page and "Participation Rate" in page, "Department Statistics panel is shown with the reference fields")
# ---- the four old charts are gone, the two new canvases are there
for old in ["chart-participation", "chart-departments", "chart-status", "chart-finance"]:
    check(old not in page, f"old chart {old} removed")
check("chart-budget-trend" in page and "chart-open-participation" in page, "the two replacement chart canvases are present")
check("Budget and Expenses Monitoring" in page and "Open Election Voting Participation" in page, "chart titles are present")
# ---- Recent actions / Recent logins still present
check("Recent actions" in page and "Recent logins" in page, "Recent actions and Recent logins are still on the page")

# ---- department statistics equal the database
with app.app_context(): d = get_dashboard_stats()
rows = fetch_all("SELECT d.id, d.name FROM departments d WHERE d.is_active=1 ORDER BY d.id")
check([x["name"] for x in d["department_stats"]] == [r["name"] for r in rows], "one card per active department, in order")
for dept in d["department_stats"]:
    e = fetch_one("SELECT p.eligible_voters ev, p.votes_cast vc FROM elections e JOIN v_election_participation p ON p.election_id=e.id JOIN departments dd ON dd.id=e.department_id WHERE dd.name=%s AND e.status='open' ORDER BY e.start_at DESC LIMIT 1", (dept["name"],))
    if e: check(dept["status"] == "open" and dept["eligible"] == int(e["ev"]) and dept["cast"] == int(e["vc"]) and dept["rate"] == (round(int(e["vc"]) * 100 / int(e["ev"]), 1) if int(e["ev"]) else 0.0), f"{dept['name']}: eligible/cast/rate equal the database ({dept['eligible']}/{dept['cast']}/{dept['rate']}%)")
    else: check(dept["status_label"] in ("NO ELECTION", "SCHEDULED", "CLOSED", "VERIFYING", "VERIFIED", "PUBLISHED"), f"{dept['name']}: no open election -> shows {dept['status_label']}")

# ---- open-election participation chart equals the database; empty cases do not fail
op = d["charts"]["open_participation"]
db_open = fetch_all("SELECT e.name, p.eligible_voters ev, p.votes_cast vc FROM elections e JOIN v_election_participation p ON p.election_id=e.id WHERE e.status='open' ORDER BY e.end_at, e.id")
check(op["labels"] == [r["name"] for r in db_open] and op["voted"] == [int(r["vc"]) for r in db_open] and op["not_voted"] == [max(int(r["ev"]) - int(r["vc"]), 0) for r in db_open], "voted / not-yet-voted bars equal the database")
db_exec("UPDATE elections SET status='closed' WHERE status='open'")
with app.app_context(): d2 = get_dashboard_stats()
check(d2["charts"]["open_participation"]["labels"] == [] and "No election is open right now" in open("static/js/super_admin_dashboard.js").read(), "no open election: empty data, friendly message, no error")
check(c.get("/super-admin/dashboard").status_code == 200, "dashboard renders with no open election")
db_exec("INSERT INTO elections (name, department_id, school_year_id, start_at, end_at, status, created_by) SELECT 'Zero voters', d.id, (SELECT id FROM school_years WHERE status='active' LIMIT 1), NOW()-INTERVAL 1 HOUR, NOW()+INTERVAL 5 HOUR, 'open', 1 FROM departments d WHERE d.is_active=1 AND NOT EXISTS (SELECT 1 FROM students s WHERE s.department_id=d.id AND s.status='active') LIMIT 1")
with app.app_context(): d3 = get_dashboard_stats()
check(all(isinstance(v, (int, float)) for v in d3["charts"]["open_participation"]["rates"]) and c.get("/super-admin/dashboard").status_code == 200, "an election with no eligible students gives 0.0% (no division by zero)")

# ---- budget line chart equals the database
bt = d["charts"]["budget_trend"]
check(len(bt["labels"]) == len(bt["budgets"]) == len(bt["expenses"]) and 6 <= len(bt["labels"]) <= 12, "line chart has 6-12 monthly points")
tb = fetch_one("SELECT COALESCE(SUM(approved_amount),0) t FROM budgets WHERE status='approved'")["t"]; te = fetch_one("SELECT COALESCE(SUM(amount),0) t FROM expenses WHERE status='approved'")["t"]
check(float(str(bt["totals"]["budgets"])) == float(tb) and float(str(bt["totals"]["expenses"])) == float(te), "chart totals equal the approved budgets and expenses in the database")

# ---- user table: columns, order, name format, no Last Login
db_exec("UPDATE users SET first_name='Ana', middle_name='Liza', last_name='Reyes', email='ana@gmail.com' WHERE username='schooladmin'")
db_exec("UPDATE users SET first_name='Juan', middle_name=NULL, last_name='Dela Cruz', email=NULL WHERE username='officer1'")
h = c.get("/super-admin/users?per_page=50").get_data(as_text=True)
head = re.findall(r"<th[^>]*>(.*?)</th>", h.split("<thead")[1].split("</thead>")[0], re.S)
heads = [_html.unescape(re.sub(r"<[^>]+>|\s+", " ", t)).strip().replace("↑", "").replace("↓", "").strip() for t in head]
check(heads[:5] == ["Name & Email", "Username / ID", "Role", "Status", "Actions"] and len(heads) == 5, "columns are exactly: Name & Email, Username / ID, Role, Status, Actions", heads)
check("Last login" not in h and "last_login" not in h, "Last Login column is removed")
check("REYES, ANA LIZA" in h and "ana@gmail.com" in h, "name shown as LASTNAME, FIRST MIDDLE with the email below")
check("DELA CRUZ, JUAN" in h and "DELA CRUZ, JUAN " not in h and "JUAN ," not in h, "missing middle name leaves no extra space or comma")
check("No email address" in h, "missing email is shown gracefully")
check(display_name("Maria", "", "Santos") == "SANTOS, MARIA" and display_name(None, None, None, "Old Name") == "OLD NAME" and display_name(None, None, None, None) == "\u2014" and display_name("Madonna", None, None) == "MADONNA", "name formatter handles missing parts and old accounts")
for action in ["/edit", "/reset-password", "/toggle-active"]: check(action in h, f"action kept: {action}")
r = c.get("/super-admin/users?sort=last_login"); check(r.status_code == 200, "an old bookmark with sort=last_login still works")
r = c.get("/super-admin/users?sort=name&dir=asc"); names = re.findall(r'class="break-words font-semibold[^>]*>([^<]+)', r.get_data(as_text=True)); keys = [n.split(",")[0].strip().lower() for n in names]; check(len(keys) > 3 and keys == sorted(keys), "the Name column sorts by last name", keys)
# ---- phone layout hooks
check("table.rt-stack" in h and "responsive_tables.js" in h, "phone layout (stacked cards) is wired in")
for role_user, pw, url in [("schooladmin", "SchoolAdmin@123", "/school-admin/dashboard"), ("officer1", "Officer@123", "/council-officer/dashboard")]:
    cl = app.test_client(); login(cl, role_user, pw); check(cl.get(url).status_code == 200, f"{role_user} dashboard still renders")
cs = app.test_client(); login(cs, "schooladmin", "SchoolAdmin@123"); check(cs.get("/super-admin/dashboard").status_code in (302, 403), "School Admin still cannot open the Super Admin dashboard")
raise SystemExit(summary())
