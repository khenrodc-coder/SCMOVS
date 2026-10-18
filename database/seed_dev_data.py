"""Development seed data for SCMOVS (users, students, council, sample election).

Run ONCE from the project root, after schema.sql and seed.sql:
    python database/seed_dev_data.py

Passwords are hashed with Werkzeug before they are stored.
"""

import os
import sys
from datetime import datetime, timedelta

import mysql.connector
from werkzeug.security import generate_password_hash

# Allow "from config import Config" when running this file directly.
# This line MUST come before the config import below.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config


# Development-only passwords (documented in the README, never use in production)
PW_SUPER_ADMIN = "SuperAdmin@123"
PW_SCHOOL_ADMIN = "SchoolAdmin@123"
PW_OFFICER = "Officer@123"
PW_STUDENT = "Student@123"

STAFF = [
    # username, full name, role, password, email
    ("superadmin",  "System Super Admin", "super_admin",
     PW_SUPER_ADMIN,  "superadmin@scmovs.local"),
    ("schooladmin", "School Administrator", "school_admin",
     PW_SCHOOL_ADMIN, "schooladmin@scmovs.local"),
    ("officer1",    "Olivia Officer",     "council_officer",
     PW_OFFICER,      "officer1@scmovs.local"),
]

STUDENTS = [
    # student number, first, last, department code, year level, section
    ("2026-0001", "Juan",   "Dela Cruz",  "COL",  "3rd Year", "BSCS-3A"),
    ("2026-0002", "Maria",  "Santos",     "COL",  "3rd Year", "BSCS-3A"),
    ("2026-0003", "Pedro",  "Reyes",      "COL",  "2nd Year", "BSCS-2B"),
    ("2026-0004", "Ana",    "Lopez",      "COL",  "4th Year", "BSCS-4A"),
    ("2026-0005", "Rosa",   "Villanueva", "COL",  "1st Year", "BSCS-1A"),
    ("2026-0006", "Mark",   "Tan",        "COL",  "3rd Year", "BSCS-3B"),
    ("HS-2026-0001", "Carlos", "Mendoza", "HS",   "Grade 10", "10-Sampaguita"),
    ("EL-2026-0001", "Liza",   "Garcia",  "ELEM", "Grade 5",  "5-Rizal"),
]

# student number -> (position name, status, platform)
CANDIDATES = [
    ("2026-0003", "President",      "approved",
     "Stronger student services and open forums."),
    ("2026-0004", "President",      "approved",
     "Better campus events and transparent spending."),
    ("2026-0002", "Vice President", "approved",
     "Support for every department and organization."),
    ("2026-0006", "Vice President", "pending",
     "More study spaces and peer tutoring."),
]


def scalar(cursor, sql, params=()):
    """Run a query that must return one row and return its first column."""
    cursor.execute(sql, params)
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            "Missing reference data. Did you import seed.sql? Query: " + sql)
    return row[0]


def main():
    conn = mysql.connector.connect(
        host=Config.DATABASE_HOST,
        port=Config.DATABASE_PORT,
        user=Config.DATABASE_USER,
        password=Config.DATABASE_PASSWORD,
        database=Config.DATABASE_NAME,
        charset="utf8mb4",
        autocommit=False,
    )
    cur = conn.cursor()

    try:
        cur.execute("SELECT id FROM users WHERE username = %s",
                    ("superadmin",))
        if cur.fetchone():
            print("Development data already exists. Nothing was changed.")
            return

        role_ids = {}
        for role_name in ("super_admin", "school_admin", "council_officer", "student"):
            role_ids[role_name] = scalar(
                cur, "SELECT id FROM roles WHERE name = %s", (role_name,))

        dept_ids = {}
        for code in ("ELEM", "HS", "COL"):
            dept_ids[code] = scalar(
                cur, "SELECT id FROM departments WHERE code = %s", (code,))

        cur.execute(
            "SELECT id, start_date, end_date FROM school_years WHERE status = 'active'")
        year_row = cur.fetchone()
        if year_row is None:
            raise RuntimeError(
                "No active school year found. Did you import seed.sql?")
        school_year_id, year_start, year_end = year_row

        # ---- Staff users ----
        user_ids = {}
        for username, full_name, role, password, email in STAFF:
            cur.execute(
                "INSERT INTO users (username, email, password_hash, full_name, first_name, last_name, role_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (username, email, generate_password_hash(password), full_name,
                 full_name.split(" ", 1)[0], full_name.split(" ", 1)[1] if " " in full_name else None, role_ids[role]),
            )
            user_ids[username] = cur.lastrowid

        admin_id = user_ids["schooladmin"]

        # ---- Students (each gets a login account; username = student number) ----
        student_ids = {}
        for number, first, last, dept_code, year_level, section in STUDENTS:
            cur.execute(
                "INSERT INTO users (username, password_hash, full_name, first_name, last_name, role_id) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (number, generate_password_hash(PW_STUDENT),
                 f"{first} {last}", first, last, role_ids["student"]),
            )
            new_user_id = cur.lastrowid
            cur.execute(
                "INSERT INTO students (user_id, student_number, first_name, last_name, department_id, "
                "year_level, section, school_year_id, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (new_user_id, number, first, last, dept_ids[dept_code],
                 year_level, section, school_year_id, admin_id),
            )
            student_ids[number] = cur.lastrowid

        # ---- Sample election: College, open now, closes in 30 days ----
        now = datetime.now().replace(microsecond=0)
        cur.execute(
            "INSERT INTO elections (name, department_id, school_year_id, start_at, end_at, status, created_by) "
            "VALUES (%s, %s, %s, %s, %s, 'open', %s)",
            ("College Student Council Election 2026", dept_ids["COL"], school_year_id,
             now - timedelta(days=1), now + timedelta(days=30), admin_id),
        )
        election_id = cur.lastrowid

        position_ids = {}
        for order, name in enumerate(("President", "Vice President"), start=1):
            position_id = scalar(
                cur, "SELECT id FROM positions WHERE name = %s", (name,))
            position_ids[name] = position_id
            cur.execute(
                "INSERT INTO election_positions (election_id, position_id, display_order) VALUES (%s, %s, %s)",
                (election_id, position_id, order),
            )

        # ---- Candidates ----
        for number, position_name, status, platform in CANDIDATES:
            reviewed_by = admin_id if status != "pending" else None
            reviewed_at = now if status != "pending" else None
            cur.execute(
                "INSERT INTO candidates (election_id, student_id, position_id, platform, status, "
                "reviewed_by, reviewed_at, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (election_id, student_ids[number], position_ids[position_name], platform,
                 status, reviewed_by, reviewed_at, admin_id),
            )

        # ---- Sample council with one officer ----
        cur.execute(
            "INSERT INTO councils (name, department_id, school_year_id, term_start, term_end, status, created_by) "
            "VALUES (%s, %s, %s, %s, %s, 'active', %s)",
            ("College Student Council 2026-2027", dept_ids["COL"], school_year_id,
             year_start, year_end, admin_id),
        )
        council_id = cur.lastrowid
        cur.execute(
            "INSERT INTO council_officers (council_id, user_id, student_id, position_id) "
            "VALUES (%s, %s, NULL, %s)",
            (council_id, user_ids["officer1"],
             scalar(cur, "SELECT id FROM positions WHERE name = %s", ("Secretary",))),
        )

        conn.commit()

        print("Development data created.\n")
        print("Login accounts (development only):")
        print(f"  superadmin    / {PW_SUPER_ADMIN}    (Super Admin)")
        print(f"  schooladmin   / {PW_SCHOOL_ADMIN}   (School Admin)")
        print(f"  officer1      / {PW_OFFICER}        (Council Officer)")
        print(
            f"  <student no.> / {PW_STUDENT}        (e.g. 2026-0001, HS-2026-0001, EL-2026-0001)")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
