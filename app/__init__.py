import os
from importlib import import_module
from flask import Flask, g
from flask_wtf.csrf import CSRFProtect

from config import Config

csrf = CSRFProtect()


def create_app():
    app = Flask(__name__, template_folder="../templates",
                static_folder="../static")
    app.config.from_object(Config)

    # Refuse to start without a secret key (sessions and CSRF depend on it)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY is missing. Set it in your .env file.")

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    csrf.init_app(app)

    from app import db
    db.init_app(app)

    from app.auth.services import has_permission, load_current_user
    from app.settings.services import get_branding
    app.before_request(load_current_user)

    # Close elections whose end time has passed (see app/elections/auto_close.py)
    from app.elections import auto_close
    app.before_request(auto_close.check_on_request)
    auto_close.start_background_thread(app)

    from app.main.routes import main_bp
    from app.auth.routes import auth_bp
    from app.dashboard.routes import dashboard_bp
    from app.admin.routes import admin_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)

    from app.students.routes import students_bp
    from app.departments.routes import departments_bp
    from app.school_years.routes import school_years_bp
    from app.positions.routes import positions_bp
    app.register_blueprint(students_bp)
    app.register_blueprint(departments_bp)
    app.register_blueprint(school_years_bp)
    app.register_blueprint(positions_bp)

    from app.elections.routes import elections_bp
    from app.candidates.routes import candidates_bp
    app.register_blueprint(elections_bp)
    app.register_blueprint(candidates_bp)
    from app.councils.routes import councils_bp
    app.register_blueprint(councils_bp)

    from app.events.routes import events_bp
    from app.projects.routes import projects_bp
    app.register_blueprint(events_bp)
    app.register_blueprint(projects_bp)

    from app.budgets.routes import budgets_bp
    from app.expenses.routes import expenses_bp
    from app.documents.routes import documents_bp
    app.register_blueprint(budgets_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(documents_bp)

    from app.meetings.routes import meetings_bp
    from app.reports.routes import reports_bp
    app.register_blueprint(meetings_bp)
    app.register_blueprint(reports_bp)

    from app.notifications.routes import notifications_bp
    from app.voting.routes import voting_bp
    app.register_blueprint(voting_bp)
    app.register_blueprint(notifications_bp)

    from app.audit.routes import audit_bp
    from app.archives.routes import archives_bp
    from app.settings.routes import settings_bp
    from app.backups.routes import backups_bp
    app.register_blueprint(audit_bp)
    app.register_blueprint(archives_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(backups_bp)

    from app.locations import PLACES, PROVINCE
    from app.media import media_bp, photo_url
    from app.profile.routes import profile_bp
    app.register_blueprint(media_bp)
    app.register_blueprint(profile_bp)

    from app.results.routes import results_bp
    app.register_blueprint(results_bp)

    from app.announcements.routes import announcements_bp
    app.register_blueprint(announcements_bp)

    from app.errors import register_error_handlers
    register_error_handlers(app)

    # ---- template filters ----
    @app.template_filter("money")
    def money_filter(value):
        symbol = app.config.get("CURRENCY_SYMBOL", "₱")
        return f"{symbol}{float(value or 0):,.2f}"

    @app.template_filter("dt")
    def datetime_filter(value):
        return value.strftime("%b %d, %Y %I:%M %p") if value else "Never"

    @app.template_filter("filesize")
    def filesize_filter(value):
        size = float(value or 0)
        for unit in ("B", "KB", "MB"):
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"

    @app.context_processor
    def inject_globals():
        branding = get_branding()        # system name + school name from the Settings page
        return {
            "system_name": branding["system_name"],
            "school_name": branding["school_name"],
            "system_full_name": app.config["SYSTEM_FULL_NAME"],
            "current_user": g.get("user"),
            "has_permission": has_permission,
            "photo_url": photo_url,
            "ne_places": [(place, place, "fa-location-dot") for place in PLACES],
            "ne_province": PROVINCE,
        }

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    return app
