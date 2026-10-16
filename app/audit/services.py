from flask import has_request_context, request

from datetime import date, timedelta

from app.db import fetch_all, fetch_one, get_db
from app.utils import escape_like, get_page


def log_action(user_id, action, module, description, affected_record=None, commit=True):
    """Append one row to audit_logs.

    Pass commit=False when this call is part of a bigger transaction, so the
    log row is saved or rolled back together with the change it describes.
    NEVER put passwords or secrets in the description.
    """
    ip_address = request.remote_addr if has_request_context() else None
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO audit_logs (user_id, action, module, affected_record, description, ip_address) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, action, module, affected_record,
             description[:500], ip_address),
        )
        if commit:
            db.commit()
    finally:
        cursor.close()


# ============================================================ viewer (Phase 4D)
PER_PAGE = 20


def _parse_date(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def get_filter_options():
    return {
        "modules": [r["module"] for r in fetch_all("SELECT DISTINCT module FROM audit_logs ORDER BY module")],
        "actions": [r["action"] for r in fetch_all("SELECT DISTINCT action FROM audit_logs ORDER BY action")],
    }


def list_logs(args):
    """Search and filter the audit log. Read-only: nothing here can change a log row."""
    q = args.get("q", "").strip()[:100]
    user = args.get("user", "").strip()[:60]
    module = args.get("module", "").strip()[:40]
    action = args.get("action", "").strip()[:60]
    date_from = _parse_date(args.get("date_from", ""))
    date_to = _parse_date(args.get("date_to", ""))

    where, params = [], []
    if q:
        like = "%" + escape_like(q) + "%"
        where.append("(a.description LIKE %s OR a.affected_record LIKE %s)")
        params.extend([like, like])
    if user:
        like = "%" + escape_like(user) + "%"
        where.append("(u.username LIKE %s OR u.full_name LIKE %s)")
        params.extend([like, like])
    if module:
        where.append("a.module = %s")
        params.append(module)
    if action:
        where.append("a.action = %s")
        params.append(action)
    if date_from:
        where.append("a.created_at >= %s")
        params.append(date_from)
    if date_to:
        # up to the end of the chosen day
        where.append("a.created_at < %s")
        params.append(date_to + timedelta(days=1))
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    joins = "FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id "
    total = fetch_one("SELECT COUNT(*) AS n " + joins +
                      where_sql, tuple(params))["n"]
    page, pages = get_page(args, total, PER_PAGE)
    logs = fetch_all(
        "SELECT a.id, a.created_at, a.action, a.module, a.affected_record, a.description, a.ip_address, "
        "       u.full_name, u.username " + joins + where_sql +
        " ORDER BY a.id DESC LIMIT %s OFFSET %s",
        tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE))

    base_filters = {k: v for k, v in (
        ("q", q), ("user", user), ("module", module), ("action", action),
        ("date_from", date_from.isoformat() if date_from else ""),
        ("date_to", date_to.isoformat() if date_to else "")) if v}
    return {"logs": logs, "q": q, "user": user, "module": module, "action": action,
            "date_from": base_filters.get("date_from", ""), "date_to": base_filters.get("date_to", ""),
            "page": page, "pages": pages, "total": total, "base_filters": base_filters}
