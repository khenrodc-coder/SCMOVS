"""Safe file uploads for receipts and supporting documents (requirement 53).

What is checked for every upload:
- the extension is one of pdf / png / jpg / jpeg (no executables, scripts or HTML);
- the real file CONTENT (its first bytes) is a PDF, PNG or JPEG and matches the extension;
- the size is at most 5 MB and the file is not empty;
- the name shown to people is cleaned; the name on disk is random, so the browser cannot choose a path.
Files are stored in uploads/documents/ (outside static/) and can only be downloaded through an
authorised route.
"""
import os
import re
import secrets

from flask import current_app
from werkzeug.utils import secure_filename

from app.auth.services import has_permission
from app.db import fetch_one

MAX_FILE_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {"pdf": "pdf", "png": "png",
                      "jpg": "jpg", "jpeg": "jpg"}    # extension -> real type
MIME_TYPES = {"pdf": "application/pdf",
              "png": "image/png", "jpg": "image/jpeg"}
STORED_NAME_RE = re.compile(r"^doc_[0-9a-f]{32}\.(pdf|png|jpg)$")
# Meeting files uploaded before Phase 6D were stored as <32 hex>.<ext> in uploads/meetings/. Still downloadable.
LEGACY_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(pdf|png|jpg)$")
FINANCE_PERMISSIONS = ("budgets.approve", "expenses.approve",
                       "budgets.request", "expenses.submit", "documents.manage")


def documents_folder():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "documents")
    os.makedirs(path, exist_ok=True)
    return path


def legacy_meetings_folder():
    return os.path.join(current_app.config["UPLOAD_FOLDER"], "meetings")


def folder_for(stored_filename):
    """The folder a stored file lives in, or None when the name is not one we ever generated."""
    if STORED_NAME_RE.match(stored_filename):
        return documents_folder()
    if LEGACY_NAME_RE.match(stored_filename):
        return legacy_meetings_folder()
    return None


def detect_type(first_bytes):
    """Look at the real content, not at the name the browser sent."""
    if first_bytes.startswith(b"%PDF-"):
        return "pdf"
    if first_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if first_bytes.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return None


def prepare_upload(file_storage):
    """Check an uploaded file and save it to disk.

    Returns (info, error): (None, None) when nothing was uploaded, (None, message) when the file is
    refused, otherwise (info, None) where info describes the saved file.
    """
    if file_storage is None or not file_storage.filename:
        return None, None

    shown_name = secure_filename(file_storage.filename) or "document"
    extension = shown_name.rsplit(
        ".", 1)[-1].lower() if "." in shown_name else ""
    if extension not in ALLOWED_EXTENSIONS:
        return None, "Only PDF, PNG and JPG files are allowed."

    data = file_storage.stream.read(MAX_FILE_BYTES + 1)
    if not data:
        return None, "The file is empty."
    if len(data) > MAX_FILE_BYTES:
        return None, "The file is too large (maximum 5 MB)."
    real_type = detect_type(data[:16])
    if real_type is None or real_type != ALLOWED_EXTENSIONS[extension]:
        return None, "The file content does not match its type. Please upload a real PDF, PNG or JPG."

    stored_name = f"doc_{secrets.token_hex(16)}.{real_type}"
    with open(os.path.join(documents_folder(), stored_name), "xb") as handle:      # "x" = never overwrite
        handle.write(data)
    return {"original": shown_name[:255], "stored": stored_name, "mime": MIME_TYPES[real_type], "size": len(data)}, None


def discard(info):
    """Delete a saved file again (used when the database step that should use it fails)."""
    if info:
        try:
            os.remove(os.path.join(documents_folder(), info["stored"]))
        except OSError:
            pass


def add_document_row(cursor, info, title, user_id, council_id, event_id=None, project_id=None,
                     meeting_id=None, category="other", description=None):
    """Record the file in the documents table (inside the caller's transaction). Returns the new id.

    category 'financial' is for receipts and budget files: they stay out of the document library.
    """
    cursor.execute(
        "INSERT INTO documents (title, description, category, original_filename, stored_filename, mime_type, file_size, "
        "visibility, uploaded_by, council_id, event_id, project_id, meeting_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 'private', %s, %s, %s, %s, %s)",
        (title[:200], description, category, info["original"], info["stored"], info["mime"], info["size"],
         user_id, council_id, event_id, project_id, meeting_id))
    return cursor.lastrowid


def get_document(document_id):
    return fetch_one("SELECT id, title, original_filename, stored_filename, mime_type, file_size, council_id, category "
                     "FROM documents WHERE id = %s", (document_id,))


def can_download(user, document):
    """Who may download a stored file (checked on the server for every download).

    * Finance files (receipts, budget documents): admins with a finance permission, and active
      officers of the document's own council.
    * Library files (reports, minutes, meeting files...): only people with documents.manage, that
      is council officers of the document's own council and the Super Admin. School Admin has no
      access to the council document library.
    """
    from app.proposals.services import is_admin, user_scope      # imported here to avoid a circular import
    scope = user_scope(user)
    if document["category"] == "financial":
        if not any(has_permission(code) for code in FINANCE_PERMISSIONS):
            return False
        return is_admin(user) or (scope is not None and document["council_id"] in scope)
    if not has_permission("documents.manage"):
        return False
    return scope is None or document["council_id"] in scope
