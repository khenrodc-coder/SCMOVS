import os

from flask import (Blueprint, abort, flash, g, redirect,
                   render_template, request, url_for)

from app.auth.decorators import access_required
from app.documents import services as documents
from app.meetings import services

meetings_bp = Blueprint("meetings", __name__, url_prefix="/meetings")

# Server-side: logged in -> role is super_admin or council_officer -> holds "meetings.manage".
# School Admin has no meetings permission, so it gets 403. The services check council scope again.
access = access_required(services.MANAGE_ROLES, "meetings.manage")


def get_or_404(meeting_id):
    # None also when it belongs to another council
    meeting = services.get_meeting(meeting_id, g.user)
    if meeting is None:
        abort(404)
    return meeting


def get_manageable_or_deny(meeting_id):
    """The meeting, only if this user may change it (right council, council still active)."""
    meeting = get_or_404(meeting_id)
    if not services.can_manage(g.user, meeting):
        abort(403)
    return meeting


def show_detail(meeting, minutes_text=None):
    data = services.detail_data(meeting, g.user)
    if minutes_text is not None:                  # keep what the user typed when validation failed
        data["minutes_text"] = minutes_text
    else:
        data["minutes_text"] = data["minutes"]["content"] if data["minutes"] else ""
    return render_template("meetings/detail.html", **data)


def read_form():
    return {field: request.form.get(field, "").strip() for field in services.FORM_FIELDS}


# ------------------------------------------------------------------ list / create / edit

@meetings_bp.route("")
@access
def list_page():
    data = services.list_meetings(request.args, g.user)
    return render_template("meetings/list.html", statuses=services.STATUSES,
                           can_create=bool(services.selectable_councils(g.user)), **data)


@meetings_bp.route("/new", methods=["GET", "POST"])
@access
def create():
    councils = services.selectable_councils(g.user)
    if not councils:
        flash("You need an active council before you can schedule a meeting.", "error")
        return redirect(url_for("meetings.list_page"))

    form, errors = services.empty_form(
        councils[0]["id"] if len(councils) == 1 else ""), []
    if request.method == "POST":
        form = read_form()
        errors, council_id, meeting_at = services.validate_form(
            form, g.user, "create")
        if not errors:
            meeting_id = services.create_meeting(
                form, council_id, meeting_at, g.user)
            flash("Meeting scheduled.", "success")
            return redirect(url_for("meetings.detail", meeting_id=meeting_id))
    return render_template("meetings/form.html", mode="create", form=form, errors=errors, meeting=None, councils=councils)


@meetings_bp.route("/<int:meeting_id>/edit", methods=["GET", "POST"])
@access
def edit(meeting_id):
    meeting = get_manageable_or_deny(meeting_id)
    if meeting["status"] != "scheduled":
        flash("Only a scheduled meeting can be edited.", "error")
        return redirect(url_for("meetings.detail", meeting_id=meeting_id))

    form, errors = services.form_from_meeting(meeting), []
    if request.method == "POST":
        form = read_form()
        errors, _council_id, meeting_at = services.validate_form(
            form, g.user, "edit", meeting)
        if not errors:
            problem = services.update_meeting(
                meeting, form, meeting_at, g.user)
            if problem:
                errors.append(problem)
            else:
                flash("Meeting updated.", "success")
                return redirect(url_for("meetings.detail", meeting_id=meeting_id))
    return render_template("meetings/form.html", mode="edit", form=form, errors=errors, meeting=meeting, councils=[])


# ------------------------------------------------------------------ detail and the actions on it

@meetings_bp.route("/<int:meeting_id>")
@access
def detail(meeting_id):
    return show_detail(get_or_404(meeting_id))


@meetings_bp.route("/<int:meeting_id>/status/<action>", methods=["POST"])
@access
def change_status(meeting_id, action):
    if action not in services.STATUS_ACTIONS:
        abort(404)
    meeting = get_manageable_or_deny(meeting_id)
    problem = services.change_status(meeting, action, g.user)
    flash(
        problem or f"Meeting marked as {services.STATUS_ACTIONS[action]}.", "error" if problem else "success")
    return redirect(url_for("meetings.detail", meeting_id=meeting_id))


@meetings_bp.route("/<int:meeting_id>/attendance", methods=["POST"])
@access
def attendance(meeting_id):
    meeting = get_manageable_or_deny(meeting_id)
    problem = services.save_attendance(meeting, request.form, g.user)
    flash(problem or "Attendance saved.", "error" if problem else "success")
    return redirect(url_for("meetings.detail", meeting_id=meeting_id))


@meetings_bp.route("/<int:meeting_id>/minutes", methods=["POST"])
@access
def minutes(meeting_id):
    meeting = get_manageable_or_deny(meeting_id)
    text = request.form.get("content", "")
    problem = services.save_minutes(meeting, text, g.user)
    if problem:
        flash(problem, "error")
        # re-show the page with the typed text
        return show_detail(meeting, minutes_text=text)
    flash("Minutes saved.", "success")
    return redirect(url_for("meetings.detail", meeting_id=meeting_id))


# ------------------------------------------------------------------ attachments

@meetings_bp.route("/<int:meeting_id>/files", methods=["POST"])
@access
def add_file(meeting_id):
    meeting = get_manageable_or_deny(meeting_id)
    title = request.form.get("title", "").strip()
    if len(title) > 200:
        problem = "The file title must be 200 characters or fewer."
    else:
        # Same checked upload as the document library. Downloads go through documents.download.
        info, problem = documents.prepare_upload(
            request.files.get("attachment"))
        if info is None and not problem:
            problem = "Please choose a file."
        if info is not None:
            problem = services.add_attachment(meeting, title, info, g.user)
    flash(problem or "File attached.", "error" if problem else "success")
    return redirect(url_for("meetings.detail", meeting_id=meeting_id))


@meetings_bp.route("/<int:meeting_id>/files/<int:document_id>/remove", methods=["POST"])
@access
def remove_file(meeting_id, document_id):
    meeting = get_manageable_or_deny(meeting_id)
    document = services.get_attachment(meeting["id"], document_id)
    if document is None:
        abort(404)
    problem = services.remove_attachment(meeting, document, g.user)
    flash(problem or "File removed.", "error" if problem else "success")
    return redirect(url_for("meetings.detail", meeting_id=meeting_id))
