"""Apply migration 005 to the database named in your .env. Safe to run more than once.

    python database/apply_migration_005.py

It only adds what is missing (columns, tables) and fills in split names for users that do not have them.
Nothing is dropped or overwritten. No `mysql` command-line tool is needed.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import mysql.connector  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

COLUMNS = [
    ("first_name", "VARCHAR(60) NULL AFTER full_name"),
    ("middle_name", "VARCHAR(60) NULL AFTER first_name"),
    ("last_name", "VARCHAR(60) NULL AFTER middle_name"),
    ("photo_path", "VARCHAR(255) NULL AFTER email"),
    ("theme_preference", "ENUM('light','dark') NOT NULL DEFAULT 'light'"),
]

TABLES = {
    "password_reset_tokens": """CREATE TABLE password_reset_tokens (
        id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        user_id INT UNSIGNED NOT NULL,
        token_hash CHAR(64) NOT NULL UNIQUE,
        expires_at DATETIME NOT NULL,
        used_at DATETIME NULL,
        requested_ip VARCHAR(45) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        INDEX idx_prt_user (user_id, created_at)
    ) ENGINE=InnoDB""",
    "password_reset_requests": """CREATE TABLE password_reset_requests (
        id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        ip_address VARCHAR(45) NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_prr_ip (ip_address, created_at)
    ) ENGINE=InnoDB""",
}


def main():
    conn = mysql.connector.connect(
        host=os.environ.get("DATABASE_HOST", "localhost"), port=int(os.environ.get("DATABASE_PORT", "3306")),
        user=os.environ.get("DATABASE_USER", "root"), password=os.environ.get("DATABASE_PASSWORD", ""),
        database=os.environ.get("DATABASE_NAME", "scmovs"))
    cur = conn.cursor()
    print(f"Connected to database '{conn.database}'.")

    cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users'")
    have = {r[0] for r in cur.fetchall()}
    for name, definition in COLUMNS:
        if name in have:
            print(f"  users.{name}: already there")
        else:
            cur.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
            print(f"  users.{name}: ADDED")

    cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()")
    tables = {r[0] for r in cur.fetchall()}
    for name, ddl in TABLES.items():
        if name in tables:
            print(f"  table {name}: already there")
        else:
            cur.execute(ddl)
            print(f"  table {name}: CREATED")

    # Fill split names only where they are still empty
    cur.execute("UPDATE users u JOIN students s ON s.user_id = u.id "
                "SET u.first_name = s.first_name, u.middle_name = s.middle_name, u.last_name = s.last_name "
                "WHERE u.first_name IS NULL")
    from_students = cur.rowcount
    cur.execute("""UPDATE users
        SET first_name = SUBSTRING_INDEX(TRIM(full_name), ' ', 1),
            last_name = IF(LOCATE(' ', TRIM(full_name)) > 0, SUBSTRING_INDEX(TRIM(full_name), ' ', -1), NULL),
            middle_name = IF(LENGTH(TRIM(full_name)) - LENGTH(REPLACE(TRIM(full_name), ' ', '')) >= 2,
                TRIM(SUBSTRING(TRIM(full_name), LOCATE(' ', TRIM(full_name)) + 1,
                    CHAR_LENGTH(TRIM(full_name)) - LOCATE(' ', TRIM(full_name))
                    - CHAR_LENGTH(SUBSTRING_INDEX(TRIM(full_name), ' ', -1)) - 1)), NULL)
        WHERE first_name IS NULL""")
    from_names = cur.rowcount
    conn.commit()
    print(f"  names filled: {from_students} from student records, {from_names} split from full name")
    cur.execute("SELECT COUNT(*) FROM users WHERE first_name IS NULL")
    print(f"  users still without a first name: {cur.fetchone()[0]}")
    cur.close(); conn.close()
    print("Done. Migration 005 is applied.")


if __name__ == "__main__":
    main()
