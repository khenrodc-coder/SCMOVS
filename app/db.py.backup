import mysql.connector
from flask import current_app, g


def get_db():
    """Return one MySQL connection per request (stored in flask.g).

    autocommit is OFF, so multi-step operations (voting, financial approval)
    can be wrapped in a transaction: do the queries, then db.commit(),
    or db.rollback() if anything fails.
    """
    if "db" not in g:
        cfg = current_app.config
               g.db = mysql.connector.connect(
            host=cfg["DATABASE_HOST"],
            port=cfg["DATABASE_PORT"],
            user=cfg["DATABASE_USER"],
            password=cfg["DATABASE_PASSWORD"],
            database=cfg["DATABASE_NAME"],
            charset="utf8mb4",
            autocommit=False,
        )

        # Election timestamps are stored as Philippine local time.
        # Keep this connection's NOW() consistent with those timestamps.
        cursor = g.db.cursor()
        try:
            cursor.execute("SET SESSION time_zone = '+08:00'")
        finally:
            cursor.close()


def close_db(error=None):
    db = g.pop("db", None)
    if db is not None and db.is_connected():
        db.close()


def fetch_all(sql, params=()):
    """Run a SELECT and return a list of dict rows. Always pass params as a tuple."""
    cursor = get_db().cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        cursor.close()


def fetch_one(sql, params=()):
    """Run a SELECT and return one dict row (or None)."""
    cursor = get_db().cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchone()
    finally:
        cursor.close()


def execute(sql, params=()):
    """Run a single INSERT/UPDATE/DELETE, commit, and return the new row id.

    For multi-step transactions, use get_db() directly instead.
    """
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(sql, params)
        db.commit()
        return cursor.lastrowid
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def init_app(app):
    app.teardown_appcontext(close_db)
