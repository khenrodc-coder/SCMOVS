from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.archives import services
from app.auth.decorators import access_required
from app.auth.services import is_safe_next

archives_bp = Blueprint("archives", __name__, url_prefix="/archives")

# Super Admin only (archives.manage)
manage = access_required(("super_admin",), "archives.manage")


@archives_bp.route("")
@manage
def list_page():
    data = services.list_archives(request.args)
    return render_template("archives/list.html", filters=data["base_filters"],
                           entity_types=services.ENTITY_TYPES, **data)


@archives_bp.route("/<int:archive_id>/restore", methods=["POST"])
@manage
def restore(archive_id):
    archive = services.get_archive(archive_id)
    if archive is None:
        abort(404)
    error = services.restore(archive, g.user["id"])
    flash(error or "The record was restored.", "error" if error else "success")
    target = request.form.get("next", "")
    return redirect(target if is_safe_next(target) else url_for("archives.list_page"))
