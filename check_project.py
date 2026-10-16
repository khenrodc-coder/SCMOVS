"""SCMOVS project health check. Read-only: it never changes the database.

Run from the project root with the virtual environment active:
    python check_project.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

failures = 0


def report(ok, label, detail=""):
    """Print one PASS/FAIL line and count failures."""
    global failures
    if not ok:
        failures += 1
    suffix = f"  ->  {detail}" if detail else ""
    print(("PASS  " if ok else "FAIL  ") + label + suffix)


def finish():
    print()
    if failures == 0:
        print("All checks passed. The project is ready for the next phase.")
    else:
        print(
            f"{failures} check(s) FAILED. Fix them (or send me this output) before continuing.")
    sys.exit(1 if failures else 0)


# ---------------------------------------------------------------- 1. files
REQUIRED_FILES = [
    "run.py", "config.py", "requirements.txt", ".env",
    "app/__init__.py", "app/db.py", "app/errors.py",
    "app/audit/__init__.py", "app/audit/services.py",
    "app/auth/__init__.py", "app/auth/decorators.py", "app/auth/routes.py", "app/auth/services.py",
    "app/main/__init__.py", "app/main/routes.py",
    "app/dashboard/__init__.py", "app/dashboard/routes.py",
    "app/admin/__init__.py", "app/admin/routes.py", "app/admin/services.py",
    "app/utils.py",
    "app/students/__init__.py", "app/students/routes.py", "app/students/services.py",
    "app/departments/__init__.py", "app/departments/routes.py", "app/departments/services.py",
    "app/school_years/__init__.py", "app/school_years/routes.py", "app/school_years/services.py",
    "app/positions/__init__.py", "app/positions/routes.py", "app/positions/services.py",
    "app/elections/__init__.py", "app/elections/routes.py", "app/elections/services.py",
    "app/candidates/__init__.py", "app/candidates/routes.py", "app/candidates/services.py",
    "static/js/app.js", "static/js/super_admin_dashboard.js", "static/js/students.js",
    "database/schema.sql", "database/seed.sql", "database/seed_dev_data.py",
    "database/migrations/001_positions_display_order.sql",
]
TEMPLATES = [
    "base.html", "landing.html", "profile.html",
    "auth/login.html", "auth/change_password.html",
    "errors/error.html",
    "layouts/app_layout.html", "components/pagination.html",
    "super_admin/dashboard.html", "school_admin/dashboard.html",
    "council_officer/dashboard.html", "student/dashboard.html",
    "super_admin/users/list.html", "super_admin/users/form.html",
    "super_admin/users/password_reset.html",
    "components/badges.html", "components/form_errors.html",
    "students/list.html", "students/form.html", "students/password.html",
    "departments/list.html", "departments/form.html",
    "school_years/list.html", "school_years/form.html",
    "positions/list.html", "positions/form.html",
    "elections/list.html", "elections/form.html", "elections/detail.html",
    "candidates/list.html", "candidates/form.html", "candidates/detail.html",
]

print("== 1. Files and folders ==")
for path in REQUIRED_FILES:
    exists = os.path.isfile(path)
    report(exists, path, "" if exists else "MISSING or in the wrong folder")
for name in TEMPLATES:
    path = os.path.join("templates", name)
    exists = os.path.isfile(path)
    report(exists, path, "" if exists else "MISSING or in the wrong folder")
report(not os.path.exists("templates/static"),
       "no static files inside templates/ (they belong in static/)")

# ------------------------------------------------------------ 2. app starts
print("\n== 2. Flask app ==")
try:
    from app import create_app
    app = create_app()
    report(True, "create_app() starts (SECRET_KEY is set)")
except Exception as error:
    report(False, "create_app() starts", repr(error))
    finish()

EXPECTED_ENDPOINTS = [
    "main.landing", "main.health_db",
    "auth.login", "auth.logout", "auth.change_password",
    "dashboard.home", "dashboard.super_admin_home", "dashboard.school_admin_home",
    "dashboard.council_officer_home", "dashboard.student_home", "dashboard.profile",
    "admin.users_list", "admin.user_create", "admin.user_edit",
    "admin.user_toggle_active", "admin.user_reset_password",
    "students.list_page", "students.create", "students.edit", "students.change_status", "students.reset_password",
    "departments.list_page", "departments.create", "departments.edit", "departments.toggle_active",
    "school_years.list_page", "school_years.create", "school_years.edit", "school_years.change_status",
    "positions.list_page", "positions.create", "positions.edit", "positions.toggle_active", "positions.move",
    "elections.list_page", "elections.create", "elections.detail", "elections.edit", "elections.change_status",
    "elections.add_positions", "elections.remove_position", "elections.move_position",
    "candidates.list_page", "candidates.register", "candidates.detail", "candidates.edit", "candidates.review",
]
registered = {rule.endpoint for rule in app.url_map.iter_rules()}
for endpoint in EXPECTED_ENDPOINTS:
    report(endpoint in registered, f"route registered: {endpoint}")

for name in TEMPLATES:
    try:
        app.jinja_env.get_template(name)
        report(True, f"template compiles: {name}")
    except Exception as error:
        report(False, f"template compiles: {name}", repr(error))

# --------------------------------------------------------------- 3. database
print("\n== 3. MySQL ==")
try:
    import mysql.connector
    from config import Config

    conn = mysql.connector.connect(
        host=Config.DATABASE_HOST, port=Config.DATABASE_PORT,
        user=Config.DATABASE_USER, password=Config.DATABASE_PASSWORD,
        database=Config.DATABASE_NAME, charset="utf8mb4",
    )
    cursor = conn.cursor()

    def scalar(sql, params=()):
        cursor.execute(sql, params)
        return cursor.fetchone()[0]

    version = scalar("SELECT VERSION()")
    print(f"INFO  database server version: {version}")
    if "mariadb" in version.lower():
        print("WARN  This is MariaDB. SCMOVS was designed for MySQL 8.0.16+. Tell me if the schema import errors.")
    report(True, "database connection works")
except Exception as error:
    report(False, "database connection works", repr(error))
    finish()

schema = Config.DATABASE_NAME
tables = scalar(
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE'", (schema,))
views = scalar(
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s AND table_type='VIEW'", (schema,))
triggers = scalar(
    "SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=%s", (schema,))
report(tables == 34, "34 tables exist",
       f"found {tables}" if tables != 34 else "")
report(views == 2, "2 views exist", f"found {views}" if views != 2 else "")
report(triggers == 12, "12 triggers exist",
       f"found {triggers}" if triggers != 12 else "")

has_order = scalar("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=%s "
                   "AND table_name='positions' AND column_name='display_order'", (schema,))
report(has_order == 1, "positions.display_order column exists (Phase 4B)",
       "" if has_order == 1 else "run: mysql -u root -p scmovs < database/migrations/001_positions_display_order.sql")

try:
    scalar("SELECT COUNT(*) FROM v_election_participation")
    scalar("SELECT COUNT(*) FROM v_election_results")
    report(True, "aggregate views can be queried")
except Exception as error:
    report(False, "aggregate views can be queried", repr(error))

# Reference data (from seed.sql) must match exactly; dev data (users, students) may be larger.
exact = [
    ("roles = 4", "SELECT COUNT(*) FROM roles", 4),
    ("permissions = 37", "SELECT COUNT(*) FROM permissions", 37),
    ("departments = 3", "SELECT COUNT(*) FROM departments", 3),
    ("exactly 1 active school year",
     "SELECT COUNT(*) FROM school_years WHERE status='active'", 1),
]
for label, sql, expected in exact:
    value = scalar(sql)
    report(value == expected,
           f"seed data: {label}", f"found {value}" if value != expected else "")

at_least = [
    ("users >= 11", "SELECT COUNT(*) FROM users", 11),
    ("students >= 8", "SELECT COUNT(*) FROM students", 8),
    ("role_permissions > 0", "SELECT COUNT(*) FROM role_permissions", 1),
]
for label, sql, minimum in at_least:
    value = scalar(sql)
    report(value >= minimum, f"seed data: {label}",
           f"found {value}" if value < minimum else "")

cursor.close()
conn.close()

# ------------------------------------------------------------ 4. page tests
print("\n== 4. Pages and static files (not logged in) ==")
client = app.test_client()
PAGE_TESTS = [
    ("/", 200), ("/login", 200), ("/health/db", 200),
    ("/static/js/app.js", 200), ("/static/js/super_admin_dashboard.js",
                                 200), ("/static/js/students.js", 200),
    ("/dashboard", 302), ("/super-admin/users",
                          302), ("/super-admin/dashboard", 302),
    ("/students", 302), ("/departments",
                         302), ("/school-years", 302), ("/positions", 302),
    ("/elections", 302), ("/elections/new",
                          302), ("/candidates", 302), ("/candidates/new", 302),
    ("/logout", 405), ("/this-page-does-not-exist", 404),
]
for url, expected in PAGE_TESTS:
    status = client.get(url).status_code
    report(status == expected, f"GET {url} returns {expected}",
           f"got {status}" if status != expected else "")

finish()
