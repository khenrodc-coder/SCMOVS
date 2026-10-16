from functools import wraps

from flask import abort, flash, g, redirect, request, url_for

from app.audit.services import log_action
from app.auth.services import has_permission


def _redirect_to_login():
    flash("Please log in to continue.", "warning")
    return redirect(url_for("auth.login", next=request.path))


def _deny():
    """Log the blocked attempt, then return a 403 page."""
    log_action(g.user["id"], "access_denied", "security",
               f"Blocked access to {request.path}")
    abort(403)


def login_required(view):
    """Block anonymous users."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return _redirect_to_login()
        return view(*args, **kwargs)
    return wrapped


def role_required(*allowed_roles):
    """Allow only the listed roles, e.g. @role_required("super_admin", "school_admin").

    The role comes from the database (g.user), never from the browser.
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return _redirect_to_login()
            if g.user["role"] not in allowed_roles:
                return _deny()
            return view(*args, **kwargs)
        return wrapped
    return decorator


def permission_required(code):
    """Allow only roles that hold this permission code, e.g. @permission_required("audit.view")."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return _redirect_to_login()
            if not has_permission(code):
                return _deny()
            return view(*args, **kwargs)
        return wrapped
    return decorator


def access_required(roles, code):
    """Check everything on the server, in order:
    logged in -> role is one of `roles` -> role holds permission `code`.

    Example: @access_required(("super_admin",), "departments.manage")
    """
    def decorator(view):
        return role_required(*roles)(permission_required(code)(view))
    return decorator


def access_any(roles, codes):
    """Like access_required, but the user needs at least ONE of the permission codes.

    Example: @access_any(("super_admin", "council_officer"), ("events.submit", "events.approve"))
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return _redirect_to_login()
            if g.user["role"] not in roles or not any(has_permission(code) for code in codes):
                return _deny()
            return view(*args, **kwargs)
        return wrapped
    return decorator
