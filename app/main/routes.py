import mysql.connector
from flask import Blueprint, current_app, jsonify, render_template

from app.db import fetch_one

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def landing():
    return render_template("landing.html")


@main_bp.route("/health/db")
def health_db():
    """Simple check that Flask can reach MySQL. Returns no sensitive details."""
    try:
        fetch_one("SELECT 1 AS ok")
        return jsonify({"database": "connected"})
    except mysql.connector.Error as error:
        current_app.logger.error("Database health check failed: %s", error)
        return jsonify({"database": "unavailable"}), 503
