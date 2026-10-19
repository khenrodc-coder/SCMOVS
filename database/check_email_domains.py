"""List accounts whose email is NOT @gmail.com or @holycross.edu.ph (or has no email). Changes nothing.

    python database/check_email_domains.py

Those accounts keep working. But the next time someone edits one of them (Users page, Students page or
Profile) they will be asked to enter an accepted address, and Forgot Password will not accept their address.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import mysql.connector  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
conn = mysql.connector.connect(host=os.environ.get("DATABASE_HOST", "localhost"), port=int(os.environ.get("DATABASE_PORT", "3306")),
                               user=os.environ.get("DATABASE_USER", "root"), password=os.environ.get("DATABASE_PASSWORD", ""),
                               database=os.environ.get("DATABASE_NAME", "scmovs"))
cur = conn.cursor()
cur.execute("SELECT u.username, u.full_name, r.display_name, u.email FROM users u JOIN roles r ON r.id = u.role_id "
            "WHERE u.email IS NULL OR u.email = '' OR (u.email NOT LIKE '%@gmail.com' AND u.email NOT LIKE '%@holycross.edu.ph') "
            "ORDER BY r.display_name, u.username")
rows = cur.fetchall()
print(f"{len(rows)} account(s) need a new email address the next time they are edited:\n")
for username, name, role, email in rows[:200]:
    print(f"  {role:<16} {username:<16} {name:<28} {email or '(no email)'}")
if not rows:
    print("  None. Every account already uses @gmail.com or @holycross.edu.ph.")
cur.close(); conn.close()
