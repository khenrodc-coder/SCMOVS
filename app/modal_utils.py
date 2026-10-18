"""Helpers for modal forms: the browser sends fetch() requests and gets JSON back."""
from flask import flash, jsonify, render_template, request


def wants_json():
    return request.headers.get("X-Requested-With") == "fetch"


def json_ok(message, **extra):
    return jsonify(ok=True, message=message, **extra)


def json_errors(errors, message="Please fix the highlighted fields.", status=422):
    """errors = {field_name: message}. The key '_form' is a message not tied to one field."""
    return jsonify(ok=False, message=message, errors=errors), status


def json_error_list(errors, status=422):
    """For services that return a LIST of messages: show them together at the top of the modal."""
    text = errors[0] if len(errors) == 1 else "\n".join("\u2022 " + e for e in errors)
    return json_errors({"_form": text}, message=text, status=status)


def json_redirect(message, url):
    """Success, then go to `url`. The message is flashed so it shows on the next page."""
    flash(message, "success")
    return jsonify(ok=True, message=message, redirect=url, flashed=True)


def json_reload(message):
    """Success, then reload the current page. The message is flashed so it shows after the reload."""
    flash(message, "success")
    return jsonify(ok=True, message=message, reload=True, flashed=True)


def modal_notice(message, title="This can't be done yet", icon="fa-circle-info"):
    """A small modal that only explains something (for example: no approved event exists yet)."""
    return render_template("components/_notice.html", message=message, title=title, icon=icon)
