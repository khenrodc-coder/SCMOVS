"""Open scheduled elections whose start time has arrived and close open ones whose end time has passed.
Safe to run as often as you like.

    python close_due_elections.py

Optional: schedule it (Windows Task Scheduler, or a Railway/cron job) to run every minute if you want
elections to open and close on time even when nobody is using the site and no background thread is allowed.
"""
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
os.environ["AUTO_CLOSE_THREAD"] = "false"

from app import create_app  # noqa: E402
from app.elections.auto_close import update_election_statuses  # noqa: E402

app = create_app()
with app.test_request_context("/", base_url=app.config.get("PUBLIC_BASE_URL") or "http://127.0.0.1:5000"):
    opened, closed = update_election_statuses()
    print(f"Opened {opened} election(s) whose start time had arrived. Closed {closed} election(s) whose end time had passed.")
