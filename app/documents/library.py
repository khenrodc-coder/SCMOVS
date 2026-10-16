"""Council document library.

Rules enforced here:
  * Only people with documents.manage (council officers and the Super Admin) use the library.
  * Officers see and change documents of THEIR active council only; Super Admin sees every council.
  * A document belongs to one council and may be linked to one event, project or meeting of that
    same council, or to none (a general council record).
  * Receipts and budget files (category 'financial') are never part of the library.
  * Documents are archived, never deleted. Archiving hides them from the default list.
  * The file itself is checked by documents.prepare_upload and downloaded through documents.download.
"""
from app.audit.services import log_action
from app.auth.services import has_permission
from app.db import fetch_all, fetch_one, get_db
from app.documents import services as documents
from app.proposals.services import is_admin, my_councils, user_scope
from app.utils import escape_like, get_page, to_int

PER_PAGE = 10
# 'financial' is reserved for finance records
CATEGORIES = ("report", "minutes", "proposal", "memo", "other")
CATEGORY_LABELS = {"report": "Report", "minutes": "Minutes",
                   "proposal": "Proposal", "memo": "Memo", "other": "Other"}
LINK_TYPES = ("council", "event", "project", "meeting")
LINK_LABELS = {"council": "Council record", "event": "Event",
               "project": "Project", "meeting": "Meeting"}
STATES = ("active", "archived", "all")
MANAGE_ROLES = ("super_admin", "council_officer")
FORM_FIELDS = ("council_id", "title", "category", "description", "link")
LINK_LIMIT = 200                 # most recent records offered in the drop-down, per kind

# Shared SQL: one document with its council, uploader and linked record
_FROM = ("FROM documents d JOIN councils c ON c.id = d.council_id JOIN users u ON u.id = d.uploaded_by "
         "LEFT JOIN events ev ON ev.id = d.event_id LEFT JOIN projects pr ON pr.id = d.project_id "
         "LEFT JOIN meetings mt ON mt.id = d.meeting_id ")
_COLUMNS = ("d.id, d.title, d.description, d.category, d.original_filename, d.file_size, d.created_at, d.is_archived, "
            "d.council_id, d.event_id, d.project_id, d.meeting_id, c.name AS council_name, c.status AS council_status, "
            "u.full_name AS uploaded_by_name, "
            "CASE WHEN d.event_id IS NOT NULL THEN 'event' WHEN d.project_id IS NOT NULL THEN 'project' "
            "WHEN d.meeting_id IS NOT NULL THEN 'meeting' ELSE 'council' END AS link_type, "
            "COALESCE(ev.title, pr.title, mt.title) AS link_title")
_LIBRARY_ONLY = "d.council_id IS NOT NULL AND d.category <> 'financial'"


# ================================================================ access

def selectable_councils(user):
    if is_admin(user):
        return fetch_all("SELECT id, name FROM councils WHERE status = 'active' ORDER BY name")
    return my_councils(user["id"])


def can_manage(user, document):
    """Server-side: role + permission + council scope + council still active."""
    scope = user_scope(user)
    return (user["role"] in MANAGE_ROLES and has_permission("documents.manage")
            and document["council_status"] == "active"
            and (scope is None or document["council_id"] in scope))


def get_document(document_id, user):
    """One library document, or None if it does not exist, is a finance file, or is another council's."""
    document = fetch_one(f"SELECT {_COLUMNS}, d.stored_filename, d.mime_type {_FROM} "
                         f"WHERE d.id = %s AND {_LIBRARY_ONLY}", (document_id,))
    if document is None:
        return None
    scope = user_scope(user)
    if scope is not None and document["council_id"] not in scope:
        return None
    return document


# ================================================================ listing

def _date(text):
    from datetime import datetime
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def list_documents(args, user):
    q = args.get("q", "").strip()[:100]
    category = args.get("category", "")
    link = args.get("link", "")
    state = args.get("state", "active")
    council = to_int(args.get("council"))
    date_from, date_to = _date(
        args.get("date_from")), _date(args.get("date_to"))

    where, params = [_LIBRARY_ONLY], []
    if q:
        where.append(
            "(d.title LIKE %s OR d.description LIKE %s OR d.original_filename LIKE %s)")
        params += ["%" + escape_like(q) + "%"] * 3
    scope = user_scope(user)
    if scope is None:
        if council:
            where.append("d.council_id = %s")
            params.append(council)
    elif not scope:
        where.append("1 = 0")
    else:
        where.append(f"d.council_id IN ({', '.join(['%s'] * len(scope))})")
        params += list(scope)
    if category in CATEGORIES:
        where.append("d.category = %s")
        params.append(category)
    else:
        category = ""
    if link == "council":
        where.append(
            "d.event_id IS NULL AND d.project_id IS NULL AND d.meeting_id IS NULL")
    elif link in ("event", "project", "meeting"):
        where.append(f"d.{link}_id IS NOT NULL")
    else:
        link = ""
    if state not in STATES:
        state = "active"
    if state != "all":
        where.append("d.is_archived = %s")
        params.append(1 if state == "archived" else 0)
    if date_from:
        where.append("DATE(d.created_at) >= %s")
        params.append(date_from)
    if date_to:
        where.append("DATE(d.created_at) <= %s")
        params.append(date_to)

    where_sql = " AND ".join(where)
    total = fetch_one(
        f"SELECT COUNT(*) AS n {_FROM} WHERE {where_sql}", tuple(params))["n"]
    page, pages = get_page(args, total, PER_PAGE)
    items = fetch_all(f"SELECT {_COLUMNS} {_FROM} WHERE {where_sql} ORDER BY d.created_at DESC, d.id DESC "
                      f"LIMIT %s OFFSET %s", tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE))
    filters = {k: v for k, v in (
        ("q", q), ("category", category), ("link",
                                           link), ("state", state if state != "active" else ""),
        ("council", council if scope is None else None),
        ("date_from", date_from.isoformat() if date_from else ""),
        ("date_to", date_to.isoformat() if date_to else "")) if v}
    return {"items": items, "page": page, "pages": pages, "total": total, "filters": filters, "q": q,
            "state": state, "councils": fetch_all("SELECT id, name FROM councils ORDER BY name") if scope is None else []}


# ================================================================ linking

def link_options(councils):
    """Events, projects and meetings of the given councils, for the 'Linked record' drop-down."""
    ids = [c["id"] for c in councils]
    if not ids:
        return []
    marks = ", ".join(["%s"] * len(ids))
    names = {c["id"]: c["name"] for c in councils}
    show_council = len(ids) > 1
    options = []
    for kind, table, order, extra in (("event", "events", "event_start", "AND is_archived = 0"),
                                      ("project", "projects", "created_at",
                                       "AND is_archived = 0"),
                                      ("meeting", "meetings", "meeting_at", "")):
        rows = fetch_all(f"SELECT id, title, council_id FROM {table} WHERE council_id IN ({marks}) {extra} "
                         f"ORDER BY {order} DESC LIMIT {LINK_LIMIT}", tuple(ids))
        for row in rows:
            suffix = f" - {names[row['council_id']]}" if show_council else ""
            options.append(
                {"key": f"{kind}:{row['id']}", "label": f"[{LINK_LABELS[kind]}] {row['title']}{suffix}"})
    return options


def _resolve_link(text, council_id):
    """'event:12' -> (kind, record) when that record exists in THIS council. '' -> ('council', None)."""
    if not text:
        return "council", None
    kind, _, number = text.partition(":")
    record_id = to_int(number)
    if kind not in ("event", "project", "meeting") or record_id is None:
        return None, None
    table = {"event": "events", "project": "projects",
             "meeting": "meetings"}[kind]
    record = fetch_one(
        f"SELECT id, title, council_id, status FROM {table} WHERE id = %s", (record_id,))
    if record is None or record["council_id"] != council_id:
        return None, None
    return kind, record


# ================================================================ validation

def empty_form(council_id=""):
    return {"council_id": str(council_id), "title": "", "category": "other", "description": "", "link": ""}


def form_from_document(document):
    link = ""
    for kind in ("event", "project", "meeting"):
        if document[f"{kind}_id"]:
            link = f"{kind}:{document[kind + '_id']}"
    return {"council_id": str(document["council_id"]), "title": document["title"], "category": document["category"],
            "description": document["description"] or "", "link": link}


def validate_form(form, user, mode, document=None):
    """Return (errors, council_id, link_kind, link_record). On edit the council cannot change."""
    errors = []
    if mode == "edit":
        council_id = document["council_id"]
    else:
        council_id = to_int(form["council_id"])
        if council_id not in [c["id"] for c in selectable_councils(user)]:
            errors.append("Please choose one of your active councils.")
            council_id = None
    if not 3 <= len(form["title"]) <= 200:
        errors.append("Title must be between 3 and 200 characters.")
    if form["category"] not in CATEGORIES:
        errors.append("Please choose a category.")
    if len(form["description"]) > 500:
        errors.append("Description must be 500 characters or fewer.")

    kind, record = (None, None)
    if council_id is not None:
        kind, record = _resolve_link(form["link"], council_id)
        if kind is None:
            errors.append(
                "The linked event, project or meeting must belong to the same council.")
        elif kind == "meeting" and record["status"] == "cancelled" and not (
                mode == "edit" and document["meeting_id"] == record["id"]):
            errors.append("Files cannot be attached to a cancelled meeting.")
    return errors, council_id, kind, record


def _link_columns(kind, record):
    return (record["id"] if kind == "event" else None, record["id"] if kind == "project" else None,
            record["id"] if kind == "meeting" else None)


# ================================================================ changes

def create_document(form, council_id, kind, record, info, user):
    """Save a new library document. `info` is a file already stored by documents.prepare_upload."""
    event_id, project_id, meeting_id = _link_columns(kind, record)
    db = get_db()
    cursor = db.cursor()
    try:
        document_id = documents.add_document_row(
            cursor, info, form["title"], user["id"], council_id, event_id, project_id, meeting_id,
            category=form["category"], description=form["description"] or None)
        target = f" (linked to {kind} '{record['title']}')" if record else ""
        log_action(user["id"], "document_uploaded", "documents",
                   f"Uploaded '{form['title']}' [{form['category']}]{target}",
                   affected_record=f"document:{document_id}", commit=False)
        db.commit()
        return document_id
    except Exception:
        db.rollback()
        documents.discard(info)
        raise
    finally:
        cursor.close()


def update_document(document, form, kind, record, user):
    """Change title, category, description and link. Returns an error message or None."""
    event_id, project_id, meeting_id = _link_columns(kind, record)
    db = get_db()
    db.rollback()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT is_archived FROM documents WHERE id = %s FOR UPDATE", (document["id"],))
        row = cursor.fetchone()
        if row is None:
            db.rollback()
            return "This document no longer exists."
        if row["is_archived"]:
            db.rollback()
            return "Restore an archived document before editing it."
        cursor.execute("UPDATE documents SET title = %s, category = %s, description = %s, event_id = %s, "
                       "project_id = %s, meeting_id = %s WHERE id = %s",
                       (form["title"], form["category"], form["description"] or None, event_id, project_id, meeting_id,
                        document["id"]))
        log_action(user["id"], "document_updated", "documents", f"Updated document '{form['title']}'",
                   affected_record=f"document:{document['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def set_archived(document, archived, user):
    """Archive or restore. Returns an error message or None."""
    db = get_db()
    db.rollback()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE documents SET is_archived = %s WHERE id = %s AND is_archived = %s",
                       (1 if archived else 0, document["id"], 0 if archived else 1))
        if cursor.rowcount != 1:
            db.rollback()
            return "It was already " + ("archived." if archived else "active.")
        log_action(user["id"], "document_archived" if archived else "document_restored", "documents",
                   f"{'Archived' if archived else 'Restored'} document '{document['title']}'",
                   affected_record=f"document:{document['id']}", commit=False)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
