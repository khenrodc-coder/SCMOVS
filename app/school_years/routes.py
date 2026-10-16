import mysql.connector
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth.decorators import access_required
from app.school_years import services

school_years_bp = Blueprint("school_years", __name__, url_prefix="/school-years")

manage = access_required(("super_admin",), "school_years.manage")

PAST_TENSE = {"activate": "activated", "close": "closed", "archive": "archived", "restore": "restored"}


def _read_form():
    return {key: request.form.get(key, "").strip() for key in ("name", "start_date", "end_date")}


def _get_or_404(year_id):
    year = services.get_school_year(year_id)
    if year is None:
        abort(404)
    return year


@school_years_bp.route("")
@manage
def list_page():
    return render_template("school_years/list.html", years=services.list_school_years())


@school_years_bp.route("/new", methods=["GET", "POST"])
@manage
def create():
    form, errors = {"name": "", "start_date": "", "end_date": ""}, []
    if request.method == "POST":
        form = _read_form()
        errors = services.validate_school_year(form)
        if not errors:
            try:
                services.create_school_year(form, g.user["id"])
            except mysql.connector.IntegrityError:
                errors.append("That school year already exists.")
            else:
                flash(f"School year {form['name']} was created as Upcoming.", "success")
                return redirect(url_for("school_years.list_page"))
    return render_template("school_years/form.html", mode="create", form=form, errors=errors, year=None)


@school_years_bp.route("/<int:year_id>/edit", methods=["GET", "POST"])
@manage
def edit(year_id):
    year = _get_or_404(year_id)
    if year["status"] == "archived":
        flash("Archived school years cannot be edited. Restore it first.", "error")
        return redirect(url_for("school_years.list_page"))

    form = {"name": year["name"], "start_date": str(year["start_date"]), "end_date": str(year["end_date"])}
    errors = []
    if request.method == "POST":
        form = _read_form()
        errors = services.validate_school_year(form, year_id)
        if not errors:
            try:
                services.update_school_year(year, form, g.user["id"])
            except mysql.connector.IntegrityError:
                errors.append("That school year already exists.")
            else:
                flash(f"School year {form['name']} was updated.", "success")
                return redirect(url_for("school_years.list_page"))
    return render_template("school_years/form.html", mode="edit", form=form, errors=errors, year=year)


@school_years_bp.route("/<int:year_id>/<action>", methods=["POST"])
@manage
def change_status(year_id, action):
    if action not in services.TRANSITIONS:
        abort(404)
    year = _get_or_404(year_id)
    error = services.change_status(year, action, g.user["id"])
    if error:
        flash(error, "error")
    else:
        flash(f"School year {year['name']} was {PAST_TENSE[action]}.", "success")
    return redirect(url_for("school_years.list_page"))
