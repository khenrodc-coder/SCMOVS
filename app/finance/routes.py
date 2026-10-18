from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.decorators import access_any, access_required
from app.modal_utils import json_error_list, json_ok, json_redirect, json_reload, modal_notice, wants_json
from app.documents import services as documents
from app.finance import services

ROLES = ("super_admin", "school_admin", "council_officer")


def make_blueprint(cfg):
    """Routes for one kind of finance record (budget requests or expenses). Both work the same way."""
    bp = Blueprint(cfg["blueprint"], __name__, url_prefix=cfg["prefix"])

    # Officers need the "submit" permission, admins the "approve" permission. What each person may DO is
    # checked again for every action in services.check_actor().
    view_access = access_any(ROLES, (cfg["submit_perm"], cfg["approve_perm"]))
    write_access = access_required(("council_officer",), cfg["submit_perm"])
    endpoint = cfg["blueprint"]

    def get_or_404(item_id):
        # None also when it belongs to another council
        item = services.get_item(cfg, item_id, g.user)
        if item is None:
            abort(404)
        return item

    def read_form():
        return {field: request.form.get(field, "").strip() for field in cfg["fields"]}

    def form_fragment(mode, form, item=None, activities=None):
        return render_template("finance/_form_modal.html", cfg=cfg, mode=mode, form=form, item=item,
                               activities=activities or [], activity_key=request.form.get("activity", ""))

    # ---------------------------------------------------------------- list

    @bp.route("")
    @view_access
    def list_page():
        data = services.list_items(cfg, request.args, g.user)
        return render_template("finance/list.html", cfg=cfg, filters=data["base_filters"], statuses=services.STATUSES,
                               options=services.get_filter_options(g.user), is_admin=g.user["role"] != "council_officer",
                               can_create=g.user["role"] == "council_officer", **data)

    # -------------------------------------------------------------- create

    @bp.route("/new", methods=["GET", "POST"])
    @write_access
    def create():
        activities = services.eligible_activities(g.user)
        if not activities:
            message = "Money can only be requested for an APPROVED event or project of your council. There is none yet."
            if wants_json():
                return modal_notice(message, "No approved activity yet") if request.method == "GET" else json_error_list([message], 409)
            flash(message, "error")
            return redirect(url_for(f"{endpoint}.list_page"))
        if request.method == "GET":
            if not wants_json():
                return redirect(url_for(f"{endpoint}.list_page"))
            return form_fragment("create", services.empty_form(cfg), activities=activities)

        form = read_form()
        activity = next((a for a in activities if a["key"] == request.form.get("activity", "")), None)
        errors = services.validate(cfg, form)
        if activity is None:
            errors.append("Please choose one of your approved events or projects.")
        info = None
        if not errors:
            info, upload_error = documents.prepare_upload(request.files.get("document"))
            if upload_error:
                errors.append(upload_error)
        if errors:
            return json_error_list(errors)
        item_id, error = services.create_item(cfg, form, activity, info, g.user)
        if error is not None:
            return json_error_list([error])
        return json_redirect(f"{cfg['label']} saved as a draft. Submit it when it is ready for review.",
                             url_for(f"{endpoint}.detail", item_id=item_id))

    # -------------------------------------------------------------- detail

    @bp.route("/<int:item_id>")
    @view_access
    def detail(item_id):
        item = get_or_404(item_id)
        return render_template("finance/detail.html", cfg=cfg, item=item,
                               balance=services.get_balance(
                                   item["activity_kind"], item["activity_id"]),
                               actions=services.available_actions(
                                   cfg, g.user, item),
                               can_edit=services.can_edit(cfg, g.user, item), peso=services.peso)

    # ---------------------------------------------------------------- edit

    @bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
    @write_access
    def edit(item_id):
        item = get_or_404(item_id)
        if not services.can_edit(cfg, g.user, item):
            message = f"Only the author can edit a draft or rejected {cfg['label'].lower()}."
            if wants_json():
                return modal_notice(message, "Can't edit this") if request.method == "GET" else json_error_list([message], 409)
            flash(message, "error")
            return redirect(url_for(f"{endpoint}.detail", item_id=item_id))
        if request.method == "GET":
            if not wants_json():
                return redirect(url_for(f"{endpoint}.detail", item_id=item_id))
            return form_fragment("edit", services.form_from_item(cfg, item), item)

        form = read_form()
        errors = services.validate(cfg, form)
        info = None
        if not errors:
            info, upload_error = documents.prepare_upload(request.files.get("document"))
            if upload_error:
                errors.append(upload_error)
        if errors:
            return json_error_list(errors)
        services.update_item(cfg, item, form, info, g.user)
        return json_reload(f"{cfg['label']} saved." + (" It is a draft again: submit it when ready."
                                                      if item["status"] == "rejected" else ""))

    # ------------------------------------------------------------- actions

    @bp.route("/<int:item_id>/<action>", methods=["POST"])
    @view_access
    def act(item_id, action):
        if action not in services.ACTIONS:
            abort(404)
        item = get_or_404(item_id)
        error = services.change_status(cfg, item, action, g.user, request.form.get("remarks", ""),
                                       request.form.get("approved_amount", ""))
        if error:
            flash(error, "error")
        else:
            flash(f"{cfg['label']} was {services.PAST[action]}.", "success")
        return redirect(url_for(f"{endpoint}.detail", item_id=item_id))

    return bp
