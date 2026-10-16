import os

from flask import (Blueprint, abort, flash, g, redirect,
                   render_template, request, send_from_directory, url_for)

from app.audit.services import log_action
from app.auth.decorators import access_any, access_required
from app.documents import library, services

documents_bp = Blueprint("documents", __name__, url_prefix="/documents")

# Everyone who works with finance records may ask; the document's council is checked below.
view_access = access_any(("super_admin", "school_admin",
                         "council_officer"), services.FINANCE_PERMISSIONS)


@documents_bp.route("/<int:document_id>/download")
@view_access
def download(document_id):
    document = services.get_document(document_id)
    # "Not allowed" looks exactly like "does not exist", so nobody can probe for other councils' files
    folder = services.folder_for(
        document["stored_filename"]) if document else None
    if document is None or folder is None or not services.can_download(g.user, document):
        abort(404)
    if not os.path.isfile(os.path.join(folder, document["stored_filename"])):
        abort(404)

    log_action(g.user["id"], "document_downloaded", "documents",
               f"Downloaded '{document['original_filename']}'", affected_record=f"document:{document_id}")
    response = send_from_directory(folder, document["stored_filename"], as_attachment=True,
                                   download_name=document["original_filename"], mimetype=document["mime_type"])
    response.headers["Cache-Control"] = "no-store"
    return response


# =============================================================== council document library
# Server-side: logged in -> role is super_admin or council_officer -> holds "documents.manage".
# School Admin has no documents permission, so it gets 403. The library service checks the council again.
library_access = access_required(library.MANAGE_ROLES, "documents.manage")


def get_or_404(document_id):
    # None also for finance files and other councils
    document = library.get_document(document_id, g.user)
    if document is None:
        abort(404)
    return document


def get_manageable_or_deny(document_id):
    document = get_or_404(document_id)
    if not library.can_manage(g.user, document):
        abort(403)
    return document


def read_form():
    return {field: request.form.get(field, "").strip() for field in library.FORM_FIELDS}


def form_page(mode, form, errors, document=None, councils=None):
    councils = councils if councils is not None else library.selectable_councils(
        g.user)
    return render_template("documents/form.html", mode=mode, form=form, errors=errors, document=document,
                           councils=councils, links=library.link_options(
                               councils if mode == "create" else [{"id": document["council_id"], "name": document["council_name"]}]),
                           categories=library.CATEGORIES, category_labels=library.CATEGORY_LABELS)


@documents_bp.route("")
@library_access
def list_page():
    data = library.list_documents(request.args, g.user)
    return render_template("documents/list.html", categories=library.CATEGORIES, category_labels=library.CATEGORY_LABELS,
                           link_types=library.LINK_TYPES, link_labels=library.LINK_LABELS, states=library.STATES,
                           can_create=bool(library.selectable_councils(g.user)), **data)


@documents_bp.route("/new", methods=["GET", "POST"])
@library_access
def create():
    councils = library.selectable_councils(g.user)
    if not councils:
        flash("You need an active council before you can upload documents.", "error")
        return redirect(url_for("documents.list_page"))

    form, errors = library.empty_form(
        councils[0]["id"] if len(councils) == 1 else ""), []
    if request.method == "POST":
        form = read_form()
        errors, council_id, kind, record = library.validate_form(
            form, g.user, "create")
        info = None
        if not errors:
            info, problem = services.prepare_upload(request.files.get("file"))
            if problem or info is None:
                errors.append(problem or "Please choose a file.")
        if not errors:
            document_id = library.create_document(
                form, council_id, kind, record, info, g.user)
            flash("Document uploaded.", "success")
            return redirect(url_for("documents.detail", document_id=document_id))
    return form_page("create", form, errors, councils=councils)


@documents_bp.route("/<int:document_id>")
@library_access
def detail(document_id):
    document = get_or_404(document_id)
    return render_template("documents/detail.html", document=document, can_manage=library.can_manage(g.user, document),
                           category_labels=library.CATEGORY_LABELS, link_labels=library.LINK_LABELS)


@documents_bp.route("/<int:document_id>/edit", methods=["GET", "POST"])
@library_access
def edit(document_id):
    document = get_manageable_or_deny(document_id)
    if document["is_archived"]:
        flash("Restore an archived document before editing it.", "error")
        return redirect(url_for("documents.detail", document_id=document_id))

    form, errors = library.form_from_document(document), []
    if request.method == "POST":
        form = read_form()
        errors, _council_id, kind, record = library.validate_form(
            form, g.user, "edit", document)
        if not errors:
            problem = library.update_document(
                document, form, kind, record, g.user)
            if problem:
                errors.append(problem)
            else:
                flash("Document updated.", "success")
                return redirect(url_for("documents.detail", document_id=document_id))
    return form_page("edit", form, errors, document)


@documents_bp.route("/<int:document_id>/<action>", methods=["POST"])
@library_access
def change_state(document_id, action):
    if action not in ("archive", "restore"):
        abort(404)
    document = get_manageable_or_deny(document_id)
    problem = library.set_archived(document, action == "archive", g.user)
    flash(problem or ("Document archived." if action == "archive" else "Document restored."),
          "error" if problem else "success")
    return redirect(url_for("documents.detail", document_id=document_id))
