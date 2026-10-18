"""Helpers for modal forms: the browser sends fetch() requests and gets JSON back."""
from flask import jsonify, request


def wants_json():
    return request.headers.get("X-Requested-With") == "fetch"


def json_ok(message, **extra):
    return jsonify(ok=True, message=message, **extra)


def json_errors(errors, message="Please fix the highlighted fields.", status=422):
    """errors = {field_name: message}. The key '_form' is a message not tied to one field."""
    return jsonify(ok=False, message=message, errors=errors), status
