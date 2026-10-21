"""Shared helpers for the SCMOVS test scripts. Run against a THROWAWAY database, never production:
    set DATABASE_NAME=scmovs_test   (then load schema.sql, seed.sql and run database/seed_dev_data.py on it)
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

os.environ["AUTO_CLOSE_THREAD"] = "false"      # tests call the closer directly; no background thread
from app import create_app  # noqa: E402

PASS = FAIL = 0


def check(ok, label, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(("PASS  " if ok else "FAIL  ") + label + (f"   -> {detail}" if (detail and not ok) else ""))


def summary():
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


APP = None


def new_client(**config):
    global APP
    app = create_app()
    # Tests must never use real email settings from .env: start with SMTP off, tests opt in explicitly.
    app.config.update(TESTING=False, MAIL_SERVER="", MAIL_USERNAME="", MAIL_PASSWORD="", MAIL_SENDER="")
    app.config.update(**config)
    APP = APP or app
    return app, app.test_client()


# NOTE: never keep one app context open around many test-client requests: Flask would reuse the same
# `g` for all of them and Flask-WTF's cached CSRF token would never reach the session cookie.
# These helpers open a short context per query instead.
def fetch_one(sql, params=()):
    from app import db as _db
    with APP.app_context():
        return _db.fetch_one(sql, params)


def fetch_all(sql, params=()):
    from app import db as _db
    with APP.app_context():
        return _db.fetch_all(sql, params)


def db_exec(sql, params=()):
    from app import db as _db
    with APP.app_context():
        d = _db.get_db(); cur = d.cursor(); cur.execute(sql, params); d.commit(); cur.close()


def csrf_from(html):
    m = re.search(r'name="csrf-token" content="([^"]+)"', html) or re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def login(client, username, password):
    page = client.get("/login").get_data(as_text=True)
    token = csrf_from(page)
    r = client.post("/login", data={"identifier": username, "password": password, "csrf_token": token}, follow_redirects=False)
    return r.status_code in (302, 303)


# Valid address / birthday / contact number. Forms that now require them get these unless a test opts out.
PERSONAL = {"birthdate": "2008-05-14", "contact_number": "09171234567", "barangay": "Sta. Rosa",
            "purok_street": "Purok 3", "city_municipality": "Cabanatuan City"}
_PERSONAL_URL = re.compile(r"^/(super-admin/users/new|super-admin/users/\d+/edit|students/new|students/\d+/edit|profile/edit)$")


def ajax_post(client, url, data=None, files=None, personal=True):
    """POST like modal.js does: fetch headers + CSRF token taken from a page's meta tag.

    personal=True adds valid personal details to the forms that require them (only keys the test did not set).
    """
    page = client.get("/dashboard", follow_redirects=True).get_data(as_text=True)
    token = csrf_from(page) or csrf_from(client.get("/login").get_data(as_text=True))
    headers = {"X-Requested-With": "fetch", "X-CSRFToken": token}
    payload = dict(data or {})
    if personal and _PERSONAL_URL.match(url):
        for key, value in PERSONAL.items():
            payload.setdefault(key, value)
    if files:
        payload.update(files)
    return client.post(url, data=payload, headers=headers, content_type="multipart/form-data")


def ajax_get(client, url):
    return client.get(url, headers={"X-Requested-With": "fetch"})
