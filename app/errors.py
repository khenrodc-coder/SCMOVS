from flask import render_template
from flask_wtf.csrf import CSRFError

ERROR_INFO = {
    400: ("Bad Request", "The request could not be understood. Please go back and try again."),
    401: ("Login Required", "You need to log in to access this page."),
    403: ("Access Denied", "You do not have permission to access this page."),
    413: ("File Too Large", "The upload is too large. Please choose a file of 5 MB or less."),
    404: ("Page Not Found", "The page you are looking for does not exist."),
    500: ("Server Error", "Something went wrong on our side. Please try again later."),
}


def _render(code, message=None):
    title, default_message = ERROR_INFO[code]
    return render_template(
        "errors/error.html", code=code, title=title, message=message or default_message
    ), code


def register_error_handlers(app):
    for code in ERROR_INFO:
        # Default argument (c=code) captures the current loop value
        app.register_error_handler(code, lambda e, c=code: _render(c))

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        return _render(400, "Your form session expired or was invalid. Please refresh the page and try again.")
