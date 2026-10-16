from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.decorators import access_required
from app.db import fetch_one
from app.settings import services

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

# Super Admin only (settings.manage)
manage = access_required(("super_admin",), "settings.manage")


def _page(errors=None, submitted=None, open_category=None):
    values = services.get_values()
    if submitted:                                    # keep what the admin typed when there are errors
        for d in services.SETTINGS:
            if d["category"] == open_category:
                values[d["key"]] = (submitted.get(
                    d["key"]) == "true") if d["type"] == "bool" else submitted.get(d["key"], "")
    academic = {
        "departments": fetch_one("SELECT COUNT(*) AS n FROM departments WHERE is_active = 1")["n"],
        "active_year": (fetch_one("SELECT name FROM school_years WHERE status = 'active'") or {}).get("name"),
    }
    return render_template("settings/index.html", categories=services.CATEGORIES, definitions=services.SETTINGS,
                           values=values, errors=errors or [], open_category=open_category, academic=academic)


@settings_bp.route("")
@manage
def index():
    return _page()


@settings_bp.route("/<category>", methods=["POST"])
@manage
def save(category):
    if category not in services.EDITABLE_CATEGORIES:
        abort(404)
    clean, errors = services.parse_category(category, request.form)
    if errors:
        return _page(errors, request.form, category)
    changed = services.save_category(category, clean, g.user["id"])
    flash("Settings saved." if changed else "No changes to save.",
          "success" if changed else "info")
    return redirect(url_for("settings.index"))
