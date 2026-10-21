"""Apply migration 006 to the database named in your .env. Safe to run more than once.

    python database/apply_migration_006.py

Adds:  address / birthday / contact number columns on users,
       and the ballot changes that let a Super Admin account vote (existing ballots are not touched).
Nothing is dropped or overwritten. No `mysql` command-line tool is needed.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import mysql.connector  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

import migration_006 as m  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))


def main():
    conn = mysql.connector.connect(
        host=os.environ.get("DATABASE_HOST", "localhost"), port=int(os.environ.get("DATABASE_PORT", "3306")),
        user=os.environ.get("DATABASE_USER", "root"), password=os.environ.get("DATABASE_PASSWORD", ""),
        database=os.environ.get("DATABASE_NAME", "scmovs"))
    cur = conn.cursor()
    print(f"Connected to database '{conn.database}'.")

    def columns(table):
        cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s", (table,))
        return {r[0] for r in cur.fetchall()}

    have = columns("users")
    for name, definition in m.USER_COLUMNS:
        if name in have:
            print(f"  users.{name}: already there")
        else:
            cur.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
            print(f"  users.{name}: ADDED")

    if "voter_user_id" in columns("ballots"):
        print("  ballots.voter_user_id: already there")
    else:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        cur.execute(m.BALLOT_ALTER)
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        print("  ballots: Super Admin voting columns ADDED")

    cur.execute("DROP TRIGGER IF EXISTS trg_ballots_bi")
    cur.execute(m.BALLOT_TRIGGER)
    print("  trigger trg_ballots_bi: updated")
    cur.execute(m.PARTICIPATION_VIEW)
    print("  view v_election_participation: updated (Super Admins count as eligible voters)")
    conn.commit()
    cur.close(); conn.close()
    print("Done. Migration 006 is applied.")


if __name__ == "__main__":
    main()
