"""Image uploads (profile and candidate photos).

* The real file type is detected from the file's own bytes (magic numbers). The browser's
  filename and MIME type are never trusted.
* Files get random names and live under uploads/<kind>/, outside static/.
* They are served only to logged-in users through /media/<kind>/<filename>.
"""
import os
import re
import secrets

from flask import Blueprint, abort, current_app, send_from_directory, url_for

from app.auth.decorators import login_required

media_bp = Blueprint("media", __name__, url_prefix="/media")

KINDS = ("profiles", "candidates")
SAFE_NAME_RE = re.compile(r"^[a-f0-9]{32}\.(jpg|png|webp)$")
EXT_FOR = {"jpeg": "jpg", "png": "png", "webp": "webp"}
ALLOWED_LABEL = "JPG, JPEG, PNG or WebP"


def detect_image_type(head):
    """Return 'jpeg', 'png', 'webp' or None from the first bytes of a file."""
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _folder(kind):
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], kind)
    os.makedirs(path, exist_ok=True)
    return path


def save_image(file_storage, kind):
    """Validate and store an uploaded image. Returns (relative_path, None) or (None, error)."""
    if kind not in KINDS:
        raise ValueError("Unknown upload kind")
    if file_storage is None or not getattr(file_storage, "filename", ""):
        return None, "Please choose an image file."

    limit = current_app.config["MAX_IMAGE_BYTES"]
    data = file_storage.stream.read(limit + 1)          # never read more than limit + 1 bytes
    if not data:
        return None, "The selected file is empty."
    if len(data) > limit:
        return None, f"The image is too large. The maximum size is {limit // (1024 * 1024)} MB."
    kind_found = detect_image_type(data[:16])
    if kind_found is None:
        return None, f"That file is not a valid image. Allowed types: {ALLOWED_LABEL}."

    name = f"{secrets.token_hex(16)}.{EXT_FOR[kind_found]}"
    with open(os.path.join(_folder(kind), name), "wb") as handle:
        handle.write(data)
    return f"{kind}/{name}", None


def delete_image(relative_path):
    """Remove a stored image. Only paths shaped exactly like ours are ever touched."""
    if not relative_path or "/" not in relative_path:
        return
    kind, _, name = relative_path.partition("/")
    if kind not in KINDS or not SAFE_NAME_RE.match(name):
        return
    try:
        os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], kind, name))
    except OSError:
        pass


def photo_url(relative_path):
    """Template helper: URL for a stored photo, or None (templates then show the default avatar)."""
    if not relative_path or "/" not in relative_path:
        return None
    kind, _, name = relative_path.partition("/")
    if kind not in KINDS or not SAFE_NAME_RE.match(name):
        return None
    return url_for("media.serve", kind=kind, filename=name)


@media_bp.route("/<kind>/<filename>")
@login_required
def serve(kind, filename):
    if kind not in KINDS or not SAFE_NAME_RE.match(filename):
        abort(404)
    response = send_from_directory(_folder(kind), filename)
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response
