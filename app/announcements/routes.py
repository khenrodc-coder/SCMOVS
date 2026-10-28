from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.decorators import access_required, login_required
from app.announcements import services

announcements_bp = Blueprint(
    "announcements", __name__, url_prefix="/announcements")

# Reading: any logged-in person, but only the announcements meant for them (see services.VISIBLE_SQL).
# Managing: School Admin and Super Admin, who hold "announcements.manage". Checked on the server for every route.
manage_access = access_required(
    ("school_admin", "super_admin"), "announcements.manage")


def read_form():
    return {field: request.form.get(field, "").strip() for field in services.FORM_FIELDS}


# ================================================================ reading

@announcements_bp.route("")
@login_required
def list_page():
    return render_template("announcements/list.html", labels=services.AUDIENCE_LABELS,
                           **services.list_visible(g.user, request.args))


@announcements_bp.route("/<int:announcement_id>")
@login_required
def read(announcement_id):
    announcement = services.get_visible(g.user, announcement_id)
    if announcement is None:                 # not meant for this person looks exactly like "does not exist"
        abort(404)
    return render_template("announcements/read.html", a=announcement, labels=services.AUDIENCE_LABELS)


# ================================================================ managing

def get_or_404(announcement_id):
    announcement = services.get_announcement(announcement_id)
    if announcement is None:
        abort(404)
    return announcement


@announcements_bp.route("/manage")
@manage_access
def manage_list():
    return render_template("announcements/manage_list.html", statuses=services.STATUSES, audiences=services.AUDIENCES,
                           labels=services.AUDIENCE_LABELS, **services.list_for_manage(request.args))


@announcements_bp.route("/manage/new", methods=["GET", "POST"])
@manage_access
def manage_create():
    form, errors = services.empty_form(), []
    if request.method == "POST":
        form = read_form()
        errors, values = services.validate_form(form)
        if not errors:
            new_id = services.create(values, g.user)
            flash(
                "Announcement saved as a draft. Publish it when it is ready.", "success")
            return redirect(url_for("announcements.manage_detail", announcement_id=new_id))
    return render_template("announcements/form.html", mode="create", form=form, errors=errors, a=None,
                           audiences=services.AUDIENCES, departments=services.departments())


@announcements_bp.route("/manage/<int:announcement_id>")
@manage_access
def manage_detail(announcement_id):
    announcement = get_or_404(announcement_id)
    return render_template("announcements/manage_detail.html", a=announcement, labels=services.AUDIENCE_LABELS,
                           reach=services.audience_size(announcement))


@announcements_bp.route("/manage/<int:announcement_id>/edit", methods=["GET", "POST"])
@manage_access
def manage_edit(announcement_id):
    announcement = get_or_404(announcement_id)
    if announcement["status"] == "archived":
        flash("An archived announcement cannot be edited. Restore it first.", "error")
        return redirect(url_for("announcements.manage_detail", announcement_id=announcement_id))
    form, errors = services.form_from_announcement(announcement), []
    if request.method == "POST":
        form = read_form()
        errors, values = services.validate_form(form, announcement)
        if not errors:
            problem = services.update(announcement_id, values, g.user)
            if problem:
                errors.append(problem)
            else:
                flash("Announcement updated.", "success")
                return redirect(url_for("announcements.manage_detail", announcement_id=announcement_id))
    return render_template("announcements/form.html", mode="edit", form=form, errors=errors, a=announcement,
                           audiences=services.AUDIENCES, departments=services.departments())


@announcements_bp.route("/manage/<int:announcement_id>/<action>", methods=["POST"])
@manage_access
def manage_state(announcement_id, action):
    if action not in services.ACTIONS:
        abort(404)
    get_or_404(announcement_id)
    problem = services.change_status(announcement_id, action, g.user)
    flash(
        problem or f"Announcement {services.PAST[action]}.", "error" if problem else "success")
    return redirect(url_for("announcements.manage_detail", announcement_id=announcement_id))
