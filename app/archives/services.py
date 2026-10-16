from app.db import fetch_all, fetch_one
from app.utils import get_page

PER_PAGE = 10
ENTITY_TYPES = ("election", "school_year", "council",
                "event", "project", "student", "other")
# Types that can be restored from this page today. Councils, events and projects
# get their archive/restore actions when those modules are built (Phases 5 and 6).
RESTORABLE = ("election", "school_year", "council",
              "event", "project", "student")


def list_archives(args):
    entity_type = args.get("type", "")
    if entity_type not in ENTITY_TYPES:
        entity_type = ""
    state = args.get("state", "")
    if state not in ("archived", "restored"):
        state = ""

    where, params = [], []
    if entity_type:
        where.append("a.entity_type = %s")
        params.append(entity_type)
    if state == "archived":
        where.append("a.restored_at IS NULL")
    elif state == "restored":
        where.append("a.restored_at IS NOT NULL")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    joins = (
        "FROM archives a "
        "LEFT JOIN users ab ON ab.id = a.archived_by LEFT JOIN users rb ON rb.id = a.restored_by "
        "LEFT JOIN elections e ON a.entity_type = 'election' AND e.id = a.entity_id "
        "LEFT JOIN school_years sy ON a.entity_type = 'school_year' AND sy.id = a.entity_id "
        "LEFT JOIN councils co ON a.entity_type = 'council' AND co.id = a.entity_id "
        "LEFT JOIN students s ON a.entity_type = 'student' AND s.id = a.entity_id "
        "LEFT JOIN events ev ON a.entity_type = 'event' AND ev.id = a.entity_id "
        "LEFT JOIN projects pr ON a.entity_type = 'project' AND pr.id = a.entity_id ")
    total = fetch_one("SELECT COUNT(*) AS n " + joins +
                      where_sql, tuple(params))["n"]
    page, pages = get_page(args, total, PER_PAGE)

    rows = fetch_all(
        "SELECT a.id, a.entity_type, a.entity_id, a.reason, a.archived_at, a.restored_at, "
        "       ab.full_name AS archived_by_name, rb.full_name AS restored_by_name, "
        "COALESCE(e.name, sy.name, co.name, ev.title, pr.title, CONCAT(s.student_number, ' - ', s.first_name, ' ', s.last_name)) AS label, "
        "COALESCE(e.status, sy.status, co.status, IF(ev.id IS NULL, NULL, IF(ev.is_archived = 1, 'archived', ev.status)), "
        "IF(pr.id IS NULL, NULL, IF(pr.is_archived = 1, 'archived', pr.status)), s.status) AS current_status "
        + joins + where_sql + " ORDER BY a.archived_at DESC, a.id DESC LIMIT %s OFFSET %s",
        tuple(params) + (PER_PAGE, (page - 1) * PER_PAGE))
    for row in rows:
        row["restorable"] = (row["restored_at"] is None and row["entity_type"] in RESTORABLE
                             and row["current_status"] == "archived")
    base_filters = {k: v for k, v in (
        ("type", entity_type), ("state", state)) if v}
    return {"archives": rows, "entity_type": entity_type, "state": state, "page": page, "pages": pages,
            "total": total, "base_filters": base_filters}


def get_archive(archive_id):
    return fetch_one("SELECT id, entity_type, entity_id, restored_at FROM archives WHERE id = %s", (archive_id,))


def restore(archive, actor_id):
    """Restore one archived record by using that module's own restore rules. Returns an error or None."""
    if archive["restored_at"] is not None:
        return "This record was already restored."
    kind, entity_id = archive["entity_type"], archive["entity_id"]

    if kind == "election":
        from app.elections import services as elections
        item = elections.get_election(entity_id)
        return "The election no longer exists." if item is None else elections.change_status(item, "restore", actor_id)
    if kind == "school_year":
        from app.school_years import services as years
        item = years.get_school_year(entity_id)
        return "The school year no longer exists." if item is None else years.change_status(item, "restore", actor_id)
    if kind == "council":
        from app.councils import services as councils
        item = councils.get_council(entity_id)
        return "The council no longer exists." if item is None else councils.change_status(item, "restore", actor_id)
    if kind in ("event", "project"):
        from app.proposals import services as proposals
        cfg = proposals.EVENT if kind == "event" else proposals.PROJECT
        item = fetch_one(f"SELECT t.*, c.name AS council_name FROM {cfg['table']} t JOIN councils c ON c.id = t.council_id "
                         f"WHERE t.id = %s", (entity_id,))
        if item is None:
            return f"The {kind} no longer exists."
        from flask import g
        return proposals.set_archived(cfg, item, False, g.user)
    if kind == "student":
        from app.students import services as students
        item = students.get_student(entity_id)
        return "The student no longer exists." if item is None else students.change_status(item, "inactive", actor_id)
    return "Restoring this type of record is not available yet."
