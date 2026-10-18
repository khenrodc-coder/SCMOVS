from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.decorators import access_any, access_required
from app.proposals import services

ROLES = ("super_admin", "school_admin", "council_officer")


def make_blueprint(cfg):
    """Build the routes for one kind of proposal (events or projects). Both behave the same way."""
    bp = Blueprint(cfg["blueprint"], __name__, url_prefix=cfg["prefix"])

    # Officers need the "submit" permission, admins the "approve" permission. Either may open the pages;
    # what each person may DO is checked again for every action in services.check_actor().
    view_access = access_any(ROLES, (cfg["submit_perm"], cfg["approve_perm"]))
    write_access = access_required(("council_officer",), cfg["submit_perm"])

    def get_or_404(item_id):
        # None also when the item belongs to another council
        item = services.get_item(cfg, item_id, g.user)
        if item is None:
            abort(404)
        return item

    def form_page(mode, form, errors, item=None, councils=None):
        return render_template("proposals/form.html", cfg=cfg, mode=mode, form=form, errors=errors, item=item,
                               councils=councils or [])

    # ---------------------------------------------------------------- list

    @bp.route("")
    @view_access
    def list_page():
        data = services.list_items(cfg, request.args, g.user)
        return render_template("proposals/list.html", cfg=cfg, filters=data["base_filters"], statuses=cfg["statuses"],
                               options=services.get_filter_options(g.user), is_admin=services.is_admin(g.user),
                               can_create=g.user["role"] == "council_officer", **data)

    # -------------------------------------------------------------- create

    @bp.route("/new", methods=["GET", "POST"])
    @write_access
    def create():
        councils = services.my_councils(g.user["id"])
        if not councils:
            flash(
                "You are not an active officer of any council, so you cannot create proposals.", "error")
            return redirect(url_for(f"{cfg['blueprint']}.list_page"))

        form, errors = services.empty_form(cfg), []
        form["council_id"] = str(councils[0]["id"])
        if request.method == "POST":
            form = {column: request.form.get(
                column, "").strip() for column in cfg["columns"]}
            form["council_id"] = request.form.get("council_id", "").strip()
            errors = services.validate(cfg, form)
            if not any(str(c["id"]) == form["council_id"] for c in councils):
                errors.append("Please choose one of your councils.")
            if not errors:
                item_id = services.create_item(
                    cfg, form, int(form["council_id"]), g.user)
                flash(
                    f"{cfg['label']} saved as a draft. Submit it when it is ready for review.", "success")
                return redirect(url_for(f"{cfg['blueprint']}.detail", item_id=item_id))
        return form_page("create", form, errors, councils=councils)

    # -------------------------------------------------------------- detail

    @bp.route("/<int:item_id>")
    @view_access
    def detail(item_id):
        item = get_or_404(item_id)
        return render_template("proposals/detail.html", cfg=cfg, item=item,
                               actions=services.available_actions(
                                   cfg, g.user, item),
                               can_edit=services.can_edit(cfg, g.user, item))

    # ---------------------------------------------------------------- edit

    @bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
    @write_access
    def edit(item_id):
        item = get_or_404(item_id)
        if not services.can_edit(cfg, g.user, item):
            flash(
                f"Only the author can edit a draft or rejected {cfg['label'].lower()}.", "error")
            return redirect(url_for(f"{cfg['blueprint']}.detail", item_id=item_id))

        form, errors = services.form_from_item(cfg, item), []
        if request.method == "POST":
            form = {column: request.form.get(
                column, "").strip() for column in cfg["columns"]}
            errors = services.validate(cfg, form)
            if not errors:
                services.update_item(cfg, item, form, g.user)
                flash(f"{cfg['label']} saved." + (" It is a draft again: submit it when ready."
                                                  if item["status"] == "rejected" else ""), "success")
                return redirect(url_for(f"{cfg['blueprint']}.detail", item_id=item_id))
        return form_page("edit", form, errors, item)

    # ------------------------------------------------------------- actions

    @bp.route("/<int:item_id>/<action>", methods=["POST"])
    @view_access
    def act(item_id, action):
        if action not in services.ACTIONS[cfg["kind"]] and action not in ("archive", "restore"):
            abort(404)
        item = get_or_404(item_id)
        if action in ("archive", "restore"):
            error = services.set_archived(
                cfg, item, action == "archive", g.user)
        else:
            error = services.change_status(cfg, item, action, g.user, request.form.get("remarks", ""),
                                           request.form.get("completion_report", ""))
        if error:
            flash(error, "error")
        else:
            flash(
                f"{cfg['label']} '{item['title']}' was {services.PAST[action]}.", "success")
        return redirect(url_for(f"{cfg['blueprint']}.detail", item_id=item_id))

    return bp
