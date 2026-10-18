import mysql.connector
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from app.modal_utils import json_error_list, json_errors, json_ok, json_redirect, json_reload, modal_notice, wants_json

from app.auth.decorators import access_required
from app.positions import services

positions_bp = Blueprint("positions", __name__, url_prefix="/positions")

# The seed gives positions.manage to Super Admin and School Admin
manage = access_required(("super_admin", "school_admin"), "positions.manage")


def _read_form():
    return {"name": request.form.get("name", "").strip(),
            "description": request.form.get("description", "").strip(),
            "seats": request.form.get("seats", "1").strip()}


def _get_or_404(position_id):
    position = services.get_position(position_id)
    if position is None:
        abort(404)
    return position


@positions_bp.route("")
@manage
def list_page():
    return render_template("positions/list.html", positions=services.list_positions())


@positions_bp.route("/new", methods=["GET", "POST"])
@manage
def create():
    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("positions.list_page"))
        return render_template("positions/_form_modal.html", mode="create", position=None,
                               form={"name": "", "description": "", "seats": "1"})
    form = _read_form()
    errors = services.validate_position(form)
    if errors:
        return json_error_list(errors)
    try:
        services.create_position(form, g.user["id"])
    except mysql.connector.IntegrityError:
        return json_errors({"name": "A position with that name already exists."})
    return json_ok(f"Position '{form['name']}' was created.")


@positions_bp.route("/<int:position_id>/edit", methods=["GET", "POST"])
@manage
def edit(position_id):
    position = _get_or_404(position_id)
    if request.method == "GET":
        if not wants_json():
            return redirect(url_for("positions.list_page"))
        return render_template("positions/_form_modal.html", mode="edit", position=position,
                               form={"name": position["name"], "description": position["description"] or "",
                                     "seats": str(position["seats"])})
    form = _read_form()
    errors = services.validate_position(form, position_id)
    if errors:
        return json_error_list(errors)
    try:
        services.update_position(position, form, g.user["id"])
    except mysql.connector.IntegrityError:
        return json_errors({"name": "A position with that name already exists."})
    return json_ok(f"Position '{form['name']}' was updated.")


@positions_bp.route("/<int:position_id>/toggle-active", methods=["POST"])
@manage
def toggle_active(position_id):
    position = _get_or_404(position_id)
    make_active = not position["is_active"]
    services.set_position_active(position, make_active, g.user["id"])
    flash(
        f"Position '{position['name']}' was {'activated' if make_active else 'deactivated'}.", "success")
    return redirect(url_for("positions.list_page"))


@positions_bp.route("/<int:position_id>/move/<direction>", methods=["POST"])
@manage
def move(position_id, direction):
    if direction not in ("up", "down"):
        abort(404)
    position = _get_or_404(position_id)
    if not services.move_position(position, direction, g.user["id"]):
        flash(
            f"'{position['name']}' is already at the {'top' if direction == 'up' else 'bottom'}.", "info")
    return redirect(url_for("positions.list_page"))
