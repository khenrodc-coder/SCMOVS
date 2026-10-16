from flask import (Blueprint, abort, flash, g, redirect, render_template, request, send_from_directory,
                   session, url_for)
from werkzeug.security import check_password_hash

from app.audit.services import log_action
from app.auth.decorators import access_required
from app.backups import services
from app.db import fetch_one

backups_bp = Blueprint("backups", __name__, url_prefix="/backups")

# Super Admin only (backups.manage)
manage = access_required(("super_admin",), "backups.manage")

CONFIRM_WORD = "RESTORE"


def _get_or_404(backup_id):
    backup = services.get_backup(backup_id)
    if backup is None:
        abort(404)
    return backup


@backups_bp.route("")
@manage
def list_page():
    data = services.list_backups(request.args)
    return render_template("backups/list.html", tools=services.tool_status(), **data)


@backups_bp.route("/create", methods=["POST"])
@manage
def create():
    note = request.form.get("note", "").strip()[:100]
    backup_id, error = services.create_backup(g.user["id"], note)
    if error:
        flash("The backup failed: " + error, "error")
    else:
        flash("The backup was created.", "success")
    return redirect(url_for("backups.list_page"))


@backups_bp.route("/<int:backup_id>/download")
@manage
def download(backup_id):
    backup = _get_or_404(backup_id)
    problem = services.verify_backup_file(backup)
    if problem:
        flash(problem, "error")
        return redirect(url_for("backups.list_page"))
    log_action(g.user["id"], "backup_downloaded", "backups", f"Downloaded backup {backup['filename']}",
               affected_record=f"backup:{backup_id}")
    response = send_from_directory(
        services.backup_folder(), backup["filename"], as_attachment=True)
    response.headers["Cache-Control"] = "no-store"
    return response


@backups_bp.route("/<int:backup_id>/restore", methods=["GET", "POST"])
@manage
def restore(backup_id):
    backup = _get_or_404(backup_id)
    if backup["status"] != "completed":
        flash("Only completed backups can be restored.", "error")
    # a backup that still holds ballot data
    problem = services.protection_problem(backup)
    if problem:
        flash(problem, "error")
        return redirect(url_for("backups.list_page"))
        return redirect(url_for("backups.list_page"))

    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        typed = request.form.get("confirm_word", "").strip()
        owner = fetch_one(
            "SELECT password_hash FROM users WHERE id = %s", (g.user["id"],))

        if typed != CONFIRM_WORD:
            error = f"Type {CONFIRM_WORD} (capital letters) to confirm."
        elif not check_password_hash(owner["password_hash"], password):
            log_action(g.user["id"], "backup_restore_denied", "backups",
                       f"Wrong password while trying to restore {backup['filename']}",
                       affected_record=f"backup:{backup_id}")
            error = "Your password is incorrect."
        else:
            error = services.restore_backup(backup, g.user)
            if error is None:
                # The data was replaced, so the old session may point to users that no longer exist
                session.clear()
                flash("The backup was restored. Please log in again.", "success")
                return redirect(url_for("auth.login"))

    return render_template("backups/restore.html", backup=backup, error=error, confirm_word=CONFIRM_WORD)
