"""Run from your project folder:   python diagnose.py
Checks files, database and the server on port 5000, then tells you what is wrong. Changes nothing."""
import os
import sys
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
problems = []
in_process_ok = False


def say(ok, text):
    print(("  OK    " if ok else "  FAIL  ") + text)
    if not ok:
        problems.append(text)


print(f"Project folder: {ROOT}\n")
print("1) Files this version needs")
need = ["static/js/app.js", "static/js/modal.js", "static/js/form_rules.js", "static/js/icon_select.js", "static/js/select_icons.js",
        "static/js/charts_common.js", "static/css/dark.css", "static/img/logo.png", "templates/components/modal.html",
        "templates/super_admin/users/_form_modal.html", "templates/profile.html", "app/media.py", "database/migrations/005_profiles_names_photos_reset.sql"]
for f in need:
    say(os.path.isfile(os.path.join(ROOT, f)), f)

print("\n2) Flask app and settings")
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from app import create_app
    app = create_app()
    say(True,
        f"app starts; static folder = {os.path.abspath(app.static_folder)}")
    say(os.path.isdir(app.static_folder), "static folder exists")
    for key in ("MAX_IMAGE_BYTES", "PASSWORD_RESET_MINUTES", "RESET_MAX_PER_IP"):
        say(key in app.config, f"config has {key}")
    client = app.test_client()
    r = client.get("/static/js/modal.js")
    in_process_ok = r.status_code == 200
    say(in_process_ok,
        f"this project serves /static/js/modal.js  (status {r.status_code})")
    r.close()
except Exception as error:                                   # noqa: BLE001
    say(False, f"app could not start: {type(error).__name__}: {error}")
    app = None

print("\n3) Database")
if app is not None:
    try:
        with app.app_context():
            from app.db import fetch_all
            cols = {r["COLUMN_NAME"] for r in fetch_all("SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                                                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users'")}
            for c in ("first_name", "middle_name", "last_name", "photo_path", "theme_preference"):
                say(c in cols, f"users.{c} exists" + (
                    "" if c in cols else "   -> run: python database/apply_migration_005.py"))
            tabs = {r["TABLE_NAME"] for r in fetch_all(
                "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()")}
            for t in ("password_reset_tokens", "password_reset_requests"):
                say(t in tabs, f"table {t} exists")
    except Exception as error:                               # noqa: BLE001
        say(False, f"database check failed: {type(error).__name__}: {error}")

print("\n4) The server that is answering on http://127.0.0.1:5000 right now")
live = {}
for path in ("/static/js/modal.js", "/static/img/logo.png", "/static/css/dark.css"):
    try:
        with urllib.request.urlopen("http://127.0.0.1:5000" + path, timeout=3) as resp:
            live[path] = (resp.status, resp.headers.get(
                "Content-Type", ""), resp.headers.get("Server", ""))
    except urllib.error.HTTPError as error:
        live[path] = (error.code, error.headers.get(
            "Content-Type", ""), error.headers.get("Server", ""))
    except Exception:                                        # noqa: BLE001
        live[path] = None
if all(v is None for v in live.values()):
    print("  (nothing is listening on port 5000: start it with  python run.py  and run this again)")
else:
    for path, v in live.items():
        say(v is not None and v[0] == 200, f"{path} -> {v}")
    missing_files = [f for f in need if f.startswith(
        "static/") and not os.path.isfile(os.path.join(ROOT, f))]
    if missing_files:
        print("\n  >>> Files are MISSING from your static folder (see section 1). The server is fine; it has nothing to serve.")
        print("  >>> Extract SCMOVS_static.zip into this project folder (so 'static' sits next to run.py), replace files, restart.")
    elif app is not None and in_process_ok and any(v is None or v[0] != 200 for v in live.values()):
        print("\n  >>> The project on disk is fine, but the server on port 5000 is NOT serving it.")
        print("  >>> An old or different copy of the app is still running. Stop it, then start this one:")
        print(
            "        netstat -ano | findstr :5000        (note the PID in the last column)")
        print("        taskkill /PID <that number> /F")
        print("        python run.py")

print(
    "\n" + ("ALL CHECKS PASSED" if not problems else f"{len(problems)} PROBLEM(S) FOUND (see FAIL lines above)"))
