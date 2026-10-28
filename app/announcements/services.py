"""Announcements (spec section 28), Phase 7C.

WHO SEES WHAT (one rule, used by the announcement pages AND the dashboards):
  all_students    -> everyone with a student record (students, and council officers who are students)
  department      -> students of that department
  council         -> council officers
  administrators  -> School Admin and Super Admin
An announcement is visible only when it is 'published' and its publication time has arrived.

LIFECYCLE (no arbitrary status changes, nothing is ever deleted)
  draft --publish--> published --archive--> archived --restore--> draft      (a draft may also be archived)
  * A draft can be edited freely.
  * A published announcement may only have its title and text corrected. Its audience and date are locked,
    because people have already been told about it.
  * Publishing notifies exactly the audience, in the same transaction, unless it is scheduled for later.
    There is no background job in SCMOVS, so a scheduled announcement sends NO notification: readers simply
    see it from its date. The form says so.
"""
from datetime import datetime, timedelta

from flask import url_for

from app.audit.services import log_action
from app.db import fetch_all, fetch_one, get_db
from app.settings.services import get_bool
from app.utils import escape_like, get_page, to_int

PER_PAGE = 10
AUDIENCES = (("all_students", "All students"), ("department", "One department"),
             ("council", "Council officers"), ("administrators", "Administrators"))
AUDIENCE_LABELS = dict(AUDIENCES)
STATUSES = ("draft", "published", "archived")
FORM_FIELDS = ("title", "content", "target_audience",
               "department_id", "publish_at")
ACTIONS = {"publish": (("draft",), "published"), "archive": (("draft", "published"), "archived"),
           "restore": (("archived",), "draft")}
PAST = {"publish": "published", "archive": "archived",
        "restore": "restored to draft"}


# ================================================================ who may read what

def viewer_profile(user):
    """The four facts that decide which announcements a person may read."""
    student = fetch_one(
        "SELECT department_id FROM students WHERE user_id = %s", (user["id"],))
    return {"is_student": 1 if student else 0, "department_id": student["department_id"] if student else None,
            "is_officer": 1 if user["role"] == "council_officer" else 0,
            "is_admin": 1 if user["role"] in ("school_admin", "super_admin") else 0}


# The single visibility rule. The four %s are: is_student, department_id, is_officer, is_admin.
VISIBLE_SQL = ("a.status = 'published' AND (a.publish_at IS NULL OR a.publish_at <= NOW()) AND ("
               "(a.target_audience = 'all_students' AND %s = 1) OR (a.target_audience = 'department' AND a.department_id = %s) "
               "OR (a.target_audience = 'council' AND %s = 1) OR (a.target_audience = 'administrators' AND %s = 1))")


def _visible_params(profile):
    return (profile["is_student"], profile["department_id"], profile["is_officer"], profile["is_admin"])


def visible_for(user, limit=4):
    """The newest announcements this person may read (used by the dashboards)."""
    return fetch_all(
        "SELECT a.id, a.title, a.content, a.publish_at, a.created_at, u.full_name AS author "
        "FROM announcements a JOIN users u ON u.id = a.author_id WHERE " + VISIBLE_SQL +
        " ORDER BY COALESCE(a.publish_at, a.created_at) DESC, a.id DESC LIMIT " +
        str(int(limit)),
        _visible_params(viewer_profile(user)))


def list_visible(user, args):
    """A page of announcements for the reader's own list, with an optional text search."""
    q = args.get("q", "").strip()[:100]
    where, params = VISIBLE_SQL, list(_visible_params(viewer_profile(user)))
    if q:
        where += " AND (a.title LIKE %s OR a.content LIKE %s)"
        params += ["%" + escape_like(q) + "%"] * 2
    total = fetch_one(
        f"SELECT COUNT(*) AS n FROM announcements a WHERE {where}", tuple(params))["n"]
    page, pages = get_page(args, total, PER_PAGE)
    items = fetch_all(
        "SELECT a.id, a.title, a.content, a.target_audience, a.publish_at, a.created_at, u.full_name AS author "
        f"FROM announcements a JOIN users u ON u.id = a.author_id WHERE {where} "
        "ORDER BY COALESCE(a.publish_at, a.created_at) DESC, a.id DESC LIMIT %s OFFSET %s",
        tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE))
    return {"items": items, "page": page, "pages": pages, "total": total, "q": q, "filters": {"q": q} if q else {}}


def get_visible(user, announcement_id):
    """One announcement, or None when it does not exist or is not meant for this person."""
    return fetch_one(
        "SELECT a.id, a.title, a.content, a.target_audience, a.department_id, a.publish_at, a.created_at, "
        "u.full_name AS author, d.name AS department FROM announcements a JOIN users u ON u.id = a.author_id "
        "LEFT JOIN departments d ON d.id = a.department_id WHERE a.id = %s AND " + VISIBLE_SQL,
        (announcement_id,) + _visible_params(viewer_profile(user)))


# ================================================================ managing (School Admin / Super Admin)

def list_for_manage(args):
    q = args.get("q", "").strip()[:100]
    status = args.get("status", "")
    audience = args.get("audience", "")
    where, params = ["1 = 1"], []
    if q:
        where.append("(a.title LIKE %s OR a.content LIKE %s)")
        params += ["%" + escape_like(q) + "%"] * 2
    if status in STATUSES:
        where.append("a.status = %s")
        params.append(status)
    else:
        status = ""
    if audience in AUDIENCE_LABELS:
        where.append("a.target_audience = %s")
        params.append(audience)
    else:
        audience = ""
    where_sql = " AND ".join(where)
    total = fetch_one(
        f"SELECT COUNT(*) AS n FROM announcements a WHERE {where_sql}", tuple(params))["n"]
    page, pages = get_page(args, total, PER_PAGE)
    items = fetch_all(
        "SELECT a.id, a.title, a.target_audience, a.status, a.publish_at, a.created_at, u.full_name AS author, "
        "d.name AS department, (a.publish_at IS NOT NULL AND a.publish_at > NOW()) AS is_scheduled "
        "FROM announcements a JOIN users u ON u.id = a.author_id LEFT JOIN departments d ON d.id = a.department_id "
        f"WHERE {where_sql} ORDER BY a.created_at DESC, a.id DESC LIMIT %s OFFSET %s",
        tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE))
    return {"items": items, "page": page, "pages": pages, "total": total, "q": q, "status": status, "audience": audience,
            "filters": {k: v for k, v in (("q", q), ("status", status), ("audience", audience)) if v}}


def get_announcement(announcement_id):
    return fetch_one(
        "SELECT a.*, u.full_name AS author, d.name AS department, "
        "(a.publish_at IS NOT NULL AND a.publish_at > NOW()) AS is_scheduled "
        "FROM announcements a JOIN users u ON u.id = a.author_id LEFT JOIN departments d ON d.id = a.department_id "
        "WHERE a.id = %s", (announcement_id,))


def departments():
    return fetch_all("SELECT id, name FROM departments WHERE is_active = 1 ORDER BY name")


# ---------------------------------------------------------------- the audience (who gets notified / who can read)

def audience_sql(audience, department_id):
    """(SQL returning a user_id column, params) for one audience. Active accounts only."""
    if audience == "all_students":
        return ("SELECT s.user_id AS user_id FROM students s JOIN users u ON u.id = s.user_id "
                "WHERE s.status = 'active' AND u.is_active = 1"), ()
    if audience == "department":
        return ("SELECT s.user_id AS user_id FROM students s JOIN users u ON u.id = s.user_id "
                "WHERE s.status = 'active' AND u.is_active = 1 AND s.department_id = %s"), (department_id,)
    if audience == "council":
        return ("SELECT DISTINCT co.user_id AS user_id FROM council_officers co JOIN councils c ON c.id = co.council_id "
                "JOIN users u ON u.id = co.user_id WHERE co.is_active = 1 AND c.status = 'active' AND u.is_active = 1"), ()
    return ("SELECT u.id AS user_id FROM users u JOIN roles r ON r.id = u.role_id "
            "WHERE r.name IN ('school_admin', 'super_admin') AND u.is_active = 1"), ()


def audience_size(announcement):
    sql, params = audience_sql(
        announcement["target_audience"], announcement["department_id"])
    return fetch_one(f"SELECT COUNT(*) AS n FROM ({sql}) t", params)["n"]


# ---------------------------------------------------------------- validation

def empty_form():
    return {"title": "", "content": "", "target_audience": "all_students", "department_id": "", "publish_at": ""}


def form_from_announcement(a):
    return {"title": a["title"], "content": a["content"], "target_audience": a["target_audience"],
            "department_id": str(a["department_id"] or ""),
            "publish_at": a["publish_at"].strftime("%Y-%m-%dT%H:%M") if a["publish_at"] else ""}


def validate_form(form, existing=None):
    """Return (errors, values). A published announcement only has title and content checked: the rest is locked."""
    errors = []
    title, content = form["title"], form["content"]
    if not 3 <= len(title) <= 150:
        errors.append("Title must be between 3 and 150 characters.")
    if not 10 <= len(content) <= 5000:
        errors.append(
            "The announcement text must be between 10 and 5000 characters.")
    values = {"title": title, "content": content}
    if existing is not None and existing["status"] == "published":
        values.update(target_audience=existing["target_audience"], department_id=existing["department_id"],
                      publish_at=existing["publish_at"])
        return errors, values

    audience = form["target_audience"]
    department_id = to_int(form["department_id"])
    if audience not in AUDIENCE_LABELS:
        errors.append("Please choose who the announcement is for.")
    elif audience == "department":
        if department_id is None or not fetch_one("SELECT id FROM departments WHERE id = %s AND is_active = 1", (department_id,)):
            errors.append("Please choose an active department.")
    else:
        department_id = None
    publish_at = None
    if form["publish_at"]:
        try:
            publish_at = datetime.strptime(
                form["publish_at"], "%Y-%m-%dT%H:%M")
        except ValueError:
            errors.append(
                "Please enter a valid publication date and time, or leave it empty to publish immediately.")
        else:
            now = fetch_one("SELECT NOW() AS n")["n"]
            if publish_at < now - timedelta(minutes=5):
                errors.append(
                    "The publication date cannot be in the past. Leave it empty to publish immediately.")
            elif publish_at > now + timedelta(days=730):
                errors.append(
                    "The publication date must be within 2 years from now.")
    values.update(target_audience=audience,
                  department_id=department_id, publish_at=publish_at)
    return errors, values


# ---------------------------------------------------------------- changes (each one is ONE transaction)

def create(values, user):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("INSERT INTO announcements (title, content, author_id, target_audience, department_id, status, publish_at) "
                       "VALUES (%s, %s, %s, %s, %s, 'draft', %s)",
                       (values["title"], values["content"], user["id"], values["target_audience"],
                        values["department_id"], values["publish_at"]))
        new_id = cursor.lastrowid
        log_action(user["id"], "announcement_created", "announcements",
                   f"Created announcement '{values['title']}' for {AUDIENCE_LABELS[values['target_audience']].lower()}",
                   affected_record=f"announcement:{new_id}", commit=False)
        db.commit()
        return new_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def _begin():
    db = get_db()
    db.rollback()
    db.start_transaction(isolation_level="READ COMMITTED")
    return db, db.cursor(dictionary=True)


def update(announcement_id, values, user):
    """Returns an error message or None."""
    db, cursor = _begin()
    try:
        cursor.execute(
            "SELECT status, title FROM announcements WHERE id = %s FOR UPDATE", (announcement_id,))
        row = cursor.fetchone()
        if row is None or row["status"] == "archived":
            db.rollback()
            return "An archived announcement cannot be edited. Restore it first."
        if row["status"] == "published":        # audience, department and date stay as they were
            cursor.execute("UPDATE announcements SET title = %s, content = %s WHERE id = %s",
                           (values["title"], values["content"], announcement_id))
        else:
            cursor.execute("UPDATE announcements SET title = %s, content = %s, target_audience = %s, department_id = %s, "
                           "publish_at = %s WHERE id = %s",
                           (values["title"], values["content"], values["target_audience"], values["department_id"],
                            values["publish_at"], announcement_id))
        log_action(user["id"], "announcement_updated", "announcements",
                   f"Updated announcement '{values['title']}'" + (
                       " (corrected after publication)" if row["status"] == "published" else ""),
                   affected_record=f"announcement:{announcement_id}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def change_status(announcement_id, action, user):
    """publish / archive / restore. Returns an error message or None."""
    from_statuses, new_status = ACTIONS[action]
    db, cursor = _begin()
    try:
        cursor.execute("SELECT id, title, status, target_audience, department_id, publish_at, author_id, "
                       "(publish_at IS NOT NULL AND publish_at > NOW()) AS is_scheduled FROM announcements "
                       "WHERE id = %s FOR UPDATE", (announcement_id,))
        a = cursor.fetchone()
        if a is None or a["status"] not in from_statuses:
            db.rollback()
            return f"This announcement is {a['status'] if a else 'missing'} and cannot be {PAST[action]}."
        notified, scheduled = 0, False
        if action == "publish":
            # No back-dating: a date that has already passed means "now"
            if a["publish_at"] is None or not a["is_scheduled"]:
                cursor.execute(
                    "UPDATE announcements SET status = 'published', publish_at = NOW() WHERE id = %s", (announcement_id,))
            else:
                cursor.execute(
                    "UPDATE announcements SET status = 'published' WHERE id = %s", (announcement_id,))
                scheduled = True
            if not scheduled and get_bool("notifications_enabled", True):
                sql, params = audience_sql(
                    a["target_audience"], a["department_id"])
                cursor.execute(
                    "INSERT INTO notifications (user_id, title, message, related_module, link_url) "
                    f"SELECT t.user_id, %s, %s, 'announcements', %s FROM ({sql}) t WHERE t.user_id <> %s",
                    ("New announcement", a["title"][:500], url_for(
                        "announcements.read", announcement_id=announcement_id))
                    + params + (a["author_id"],))
                notified = cursor.rowcount
        else:
            cursor.execute(
                "UPDATE announcements SET status = %s WHERE id = %s", (new_status, announcement_id))
        log_action(user["id"], f"announcement_{new_status}" if action != "restore" else "announcement_restored", "announcements",
                   f"Announcement '{a['title']}': {a['status']} -> {new_status}"
                   + (f" ({notified} notification(s) sent)" if action ==
                      "publish" and not scheduled else "")
                   + (" (scheduled: no notifications)" if action ==
                      "publish" and scheduled else ""),
                   affected_record=f"announcement:{announcement_id}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
