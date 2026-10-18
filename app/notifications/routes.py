"""Minimal notification actions (the full Notifications page comes in a later phase).

Both routes are POST-only (CSRF protected) and only ever touch the logged-in user's own rows.
"""
from flask import Blueprint, abort, flash, g, jsonify, redirect, url_for

from app.auth.decorators import login_required
from app.db import execute, fetch_all, fetch_one

notifications_bp = Blueprint(
    "notifications", __name__, url_prefix="/notifications")


def _safe_target(url):
    """Only local paths: never send a user to another site, even if a stored link were tampered with."""
    return bool(url) and url.startswith("/") and not url.startswith("//") and "\\" not in url


@notifications_bp.route("/read-all", methods=["POST"])
@login_required
def read_all():
    execute(
        "UPDATE notifications SET is_read = 1, read_at = NOW() WHERE user_id = %s AND is_read = 0", (g.user["id"],))
    flash("All notifications marked as read.", "success")
    return redirect(url_for("dashboard.home"))


@notifications_bp.route("/<int:notification_id>/open", methods=["POST"])
@login_required
def open_notification(notification_id):
    # Another user's notification looks exactly like a missing one
    row = fetch_one("SELECT id, link_url FROM notifications WHERE id = %s AND user_id = %s",
                    (notification_id, g.user["id"]))
    if row is None:
        abort(404)
    execute("UPDATE notifications SET is_read = 1, read_at = NOW() WHERE id = %s AND user_id = %s AND is_read = 0",
            (notification_id, g.user["id"]))
    return redirect(row["link_url"] if _safe_target(row["link_url"]) else url_for("dashboard.home"))


# ----------------------------------------------------------------- JSON API for the bell panel
# Every query is limited to the logged-in user's own rows (user_id = g.user["id"]); nothing here
# ever touches ballots or votes.

PANEL_LIMIT = 30


def _item(row):
    return {"id": row["id"], "title": row["title"], "message": row["message"], "is_read": bool(row["is_read"]),
            "created_at": row["created_at"].strftime("%b %d, %Y %I:%M %p"),
            "url": row["link_url"] if _safe_target(row["link_url"]) else None}


@notifications_bp.route("/api")
@login_required
def api_list():
    rows = fetch_all("SELECT id, title, message, link_url, is_read, created_at FROM notifications "
                     "WHERE user_id = %s ORDER BY created_at DESC, id DESC LIMIT %s", (g.user["id"], PANEL_LIMIT))
    unread = fetch_one("SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s AND is_read = 0", (g.user["id"],))["n"]
    response = jsonify(ok=True, unread=unread, items=[_item(r) for r in rows])
    response.headers["Cache-Control"] = "no-store"
    return response


@notifications_bp.route("/api/<int:notification_id>/read", methods=["POST"])
@login_required
def api_mark_read(notification_id):
    if fetch_one("SELECT id FROM notifications WHERE id = %s AND user_id = %s", (notification_id, g.user["id"])) is None:
        return jsonify(ok=False, message="Notification not found."), 404
    execute("UPDATE notifications SET is_read = 1, read_at = NOW() WHERE id = %s AND user_id = %s AND is_read = 0",
            (notification_id, g.user["id"]))
    unread = fetch_one("SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s AND is_read = 0", (g.user["id"],))["n"]
    return jsonify(ok=True, unread=unread)


@notifications_bp.route("/api/read-all", methods=["POST"])
@login_required
def api_mark_all_read():
    execute("UPDATE notifications SET is_read = 1, read_at = NOW() WHERE user_id = %s AND is_read = 0", (g.user["id"],))
    return jsonify(ok=True, unread=0)
