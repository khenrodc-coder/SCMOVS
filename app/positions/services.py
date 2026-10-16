from app.audit.services import log_action
from app.db import fetch_all, fetch_one, get_db
from app.utils import to_int


def list_positions():
    return fetch_all(
        "SELECT p.id, p.name, p.description, p.is_active, p.display_order, p.seats, "
        "  (SELECT COUNT(*) FROM election_positions ep WHERE ep.position_id = p.id) AS election_count "
        "FROM positions p ORDER BY p.display_order, p.id"
    )


def get_position(position_id):
    return fetch_one("SELECT id, name, description, is_active, display_order, seats FROM positions WHERE id = %s", (position_id,))


def validate_position(form, position_id=None):
    errors = []
    if not 2 <= len(form["name"]) <= 80:
        errors.append("Position name must be between 2 and 80 characters.")
    elif fetch_one("SELECT id FROM positions WHERE name = %s AND id <> %s", (form["name"], position_id or 0)):
        errors.append("A position with that name already exists.")
    if len(form["description"]) > 255:
        errors.append("The description must be 255 characters or fewer.")
    seats = to_int(form["seats"])
    if seats is None or not 1 <= seats <= 20:
        errors.append("Seats must be a whole number from 1 to 20.")
    return errors


def create_position(form, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "SELECT COALESCE(MAX(display_order), 0) + 1 FROM positions")
        next_order = cursor.fetchone()[0]
        cursor.execute("INSERT INTO positions (name, description, display_order, seats) VALUES (%s, %s, %s, %s)",
                       (form["name"], form["description"] or None, next_order, int(form["seats"])))
        new_id = cursor.lastrowid
        log_action(actor_id, "position_created", "positions", f"Created position '{form['name']}'",
                   affected_record=f"position:{new_id}", commit=False)
        db.commit()
        return new_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def update_position(position, form, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE positions SET name = %s, description = %s, seats = %s WHERE id = %s",
                       (form["name"], form["description"] or None, int(form["seats"]), position["id"]))
        log_action(actor_id, "position_updated", "positions", f"Updated position '{position['name']}'",
                   affected_record=f"position:{position['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def set_position_active(position, active, actor_id):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("UPDATE positions SET is_active = %s WHERE id = %s",
                       (1 if active else 0, position["id"]))
        log_action(actor_id, "position_activated" if active else "position_deactivated", "positions",
                   f"{'Activated' if active else 'Deactivated'} position '{position['name']}'",
                   affected_record=f"position:{position['id']}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def move_position(position, direction, actor_id):
    """Move a position one step up or down. Returns False if it is already at the edge.

    All rows are renumbered 1, 2, 3... so the order stays clean even if
    two rows ever had the same number.
    """
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "SELECT id FROM positions ORDER BY display_order, id FOR UPDATE")
        ids = [row[0] for row in cursor.fetchall()]
        index = ids.index(position["id"])
        target = index - 1 if direction == "up" else index + 1
        if target < 0 or target >= len(ids):
            db.rollback()
            return False
        ids[index], ids[target] = ids[target], ids[index]
        for number, position_id in enumerate(ids, start=1):
            cursor.execute(
                "UPDATE positions SET display_order = %s WHERE id = %s", (number, position_id))
        log_action(actor_id, "position_moved", "positions", f"Moved position '{position['name']}' {direction}",
                   affected_record=f"position:{position['id']}", commit=False)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
