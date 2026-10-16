from flask import current_app, g

from app.audit.services import log_action
from app.db import fetch_all, fetch_one, get_db

# (category stored in the database, title shown on the page)
CATEGORIES = [
    ("general", "General"),
    ("academic", "Academic"),
    ("election", "Election"),
    ("notification", "Notifications"),
    ("security", "Security"),
]

# Every editable setting. Each one is really used by the system (see "help").
# type: text | int | bool   (min/max: length for text, value for int)
SETTINGS = [
    {"key": "system_name", "category": "general", "type": "text", "min": 2, "max": 30, "default": "SCMOVS",
     "label": "System name (short)", "help": "Shown in the sidebar, page titles and the login page."},
    {"key": "school_name", "category": "general", "type": "text", "min": 2, "max": 100, "default": "Holy Cross College",
     "label": "School name", "help": "Shown on the public home page."},
    {"key": "school_address", "category": "general", "type": "text", "min": 0, "max": 200, "default": "",
     "label": "School address", "help": "Optional. Kept for reports."},

    {"key": "election_require_candidate_per_position", "category": "election", "type": "bool", "default": True,
     "label": "Every position needs an approved candidate",
     "help": "An election cannot be opened while a position has no approved candidate."},
    {"key": "election_block_pending_candidates", "category": "election", "type": "bool", "default": True,
     "label": "Pending candidates block opening",
     "help": "An election cannot be opened while candidates are still waiting for review."},

    {"key": "notifications_enabled", "category": "notification", "type": "bool", "default": True,
     "label": "Send in-app notifications",
     "help": "Candidate decisions and election open/close notices. Turn off to stop creating them."},

    {"key": "session_timeout_minutes", "category": "security", "type": "int", "min": 5, "max": 480, "default": 30,
     "label": "Session timeout (minutes of inactivity)", "help": "Users are logged out after this much inactivity."},
    {"key": "password_min_length", "category": "security", "type": "int", "min": 6, "max": 64, "default": 8,
     "label": "Minimum password length", "help": "Applies to new passwords. Letters and numbers are always required."},
    {"key": "max_failed_logins", "category": "security", "type": "int", "min": 3, "max": 10, "default": 5,
     "label": "Failed logins before lockout", "help": "The account is locked after this many wrong passwords."},
    {"key": "lockout_minutes", "category": "security", "type": "int", "min": 1, "max": 1440, "default": 15,
     "label": "Lockout length (minutes)", "help": "How long a locked account stays locked."},
]
BY_KEY = {s["key"]: s for s in SETTINGS}
EDITABLE_CATEGORIES = {s["category"] for s in SETTINGS}


# ============================================================ reading

def _stored_values():
    return {row["setting_key"]: row["setting_value"]
            for row in fetch_all("SELECT setting_key, setting_value FROM system_settings")}


def _to_display(definition, raw):
    """Turn the stored text into the value used by the page (bool/int/text), with the default as fallback."""
    if raw is None:
        return definition["default"]
    if definition["type"] == "bool":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if definition["type"] == "int":
        try:
            return int(raw)
        except ValueError:
            return definition["default"]
    return raw


def get_values():
    stored = _stored_values()
    return {d["key"]: _to_display(d, stored.get(d["key"])) for d in SETTINGS}


def get_bool(key, default=True):
    """Used by other modules, for example: if get_bool("notifications_enabled"): ..."""
    row = fetch_one(
        "SELECT setting_value FROM system_settings WHERE setting_key = %s", (key,))
    if row is None:
        return default
    return row["setting_value"].strip().lower() in ("1", "true", "yes", "on")


def get_branding():
    """System name and school name for every page. Cached for the request; safe if the database is down."""
    if "branding" not in g:
        branding = {
            "system_name": current_app.config["SYSTEM_NAME"], "school_name": "Holy Cross College"}
        try:
            values = get_values()
            branding["system_name"] = values["system_name"] or branding["system_name"]
            branding["school_name"] = values["school_name"] or branding["school_name"]
        except Exception:                                    # error pages must still render
            pass
        g.branding = branding
    return g.branding


# ============================================================ saving

def parse_category(category, form):
    """Check the submitted values of one category.

    Returns (clean, errors): clean maps key -> text to store, errors is a list of messages.
    """
    clean, errors = {}, []
    for d in (s for s in SETTINGS if s["category"] == category):
        raw = form.get(d["key"], "")
        if d["type"] == "bool":
            clean[d["key"]] = "true" if raw == "true" else "false"
        elif d["type"] == "int":
            raw = raw.strip()
            if not raw.isdigit() or not d["min"] <= int(raw) <= d["max"]:
                errors.append(
                    f"{d['label']} must be a whole number from {d['min']} to {d['max']}.")
            clean[d["key"]] = raw
        else:
            raw = raw.strip()
            if not d["min"] <= len(raw) <= d["max"]:
                errors.append(f"{d['label']} must be {d['min']}-{d['max']} characters." if d["min"]
                              else f"{d['label']} must be {d['max']} characters or fewer.")
            if any(ord(ch) < 32 for ch in raw):
                errors.append(f"{d['label']} contains invalid characters.")
            clean[d["key"]] = raw
    return clean, errors


def save_category(category, clean, actor_id):
    """Save the changed values of one category in one transaction. Returns the list of changed keys."""
    stored = _stored_values()
    changed = []
    for key, new in clean.items():
        old = stored.get(key)
        if old is None:
            old = _display_text(BY_KEY[key]["default"])
        if old != new:
            changed.append((key, old, new))
    if not changed:
        return []

    db = get_db()
    cursor = db.cursor()
    try:
        for key, _old, new in changed:
            cursor.execute(
                "INSERT INTO system_settings (setting_key, setting_value, category, updated_by) "
                "VALUES (%s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value), updated_by = VALUES(updated_by)",
                (key, new, category, actor_id))
        details = "; ".join(
            f"{key}: '{old}' -> '{new}'" for key, old, new in changed)
        log_action(actor_id, "settings_updated", "settings", f"Updated {category} settings: {details}",
                   affected_record=f"settings:{category}", commit=False)
        db.commit()
        return [key for key, _o, _n in changed]
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def _display_text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
