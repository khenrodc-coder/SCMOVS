"""Minimal notification actions (the full Notifications page comes in a later phase).

Both routes are POST-only (CSRF protected) and only ever touch the logged-in user's own rows.
"""
from flask import Blueprint, abort, flash, g, redirect, url_for

from app.auth.decorators import login_required
from app.db import execute, fetch_one

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
