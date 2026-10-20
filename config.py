import os
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # Gmail SMTP settings for password recovery
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "false").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_SENDER = os.environ.get("MAIL_SENDER", "") or os.environ.get("MAIL_USERNAME", "")
    # Address used inside emailed links (no trailing slash). Set it in .env for production.
    PUBLIC_BASE_URL = os.environ.get(
        "PUBLIC_BASE_URL", "http://127.0.0.1:5000").rstrip("/")


    # Resend HTTPS API
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
    RESEND_FROM_EMAIL = os.environ.get(
        "RESEND_FROM_EMAIL",
        "SCMOVS Support <onboarding@resend.dev>"
    )
	
    DATABASE_HOST = os.environ.get("DATABASE_HOST", "localhost")
    DATABASE_PORT = int(os.environ.get("DATABASE_PORT", "3306"))
    DATABASE_NAME = os.environ.get("DATABASE_NAME", "scmovs")
    DATABASE_USER = os.environ.get("DATABASE_USER", "root")
    DATABASE_PASSWORD = os.environ.get(
        "DATABASE_PASSWORD", "")

    # Session security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Set SESSION_COOKIE_SECURE=true in .env only when running over HTTPS
    SESSION_COOKIE_SECURE = os.environ.get(
        "SESSION_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # Uploads live OUTSIDE static/ so they are never publicly downloadable
    UPLOAD_FOLDER = (
        "/tmp/scmovs_uploads"
        if os.environ.get("VERCEL") == "1"
        else os.path.join(BASE_DIR, "uploads")
    )
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # request ceiling; images are limited to 5 MB below

    SYSTEM_NAME = "SCMOVS"
    SYSTEM_FULL_NAME = "Student Council Management and Online Voting System"

    # Backup and recovery (Phase 4D). Backups live OUTSIDE static/ so they are never public.
    BACKUP_FOLDER = (
        "/tmp/scmovs_backups"
        if os.environ.get("VERCEL") == "1"
        else os.path.join(BASE_DIR, "backups")
    )
    # Full path if the tools are not on your PATH, e.g. C:\xampp\mysql\bin\mysqldump.exe
    MYSQLDUMP_PATH = os.environ.get("MYSQLDUMP_PATH", "mysqldump")
    MYSQL_PATH = os.environ.get("MYSQL_PATH", "mysql")

    # ---- Password recovery and photo uploads (used by app/auth/recovery.py and app/media.py) ----
    PASSWORD_RESET_MINUTES = 30
    RESET_MAX_PER_IP = int(os.environ.get("RESET_MAX_PER_IP", "5"))             # per 15 minutes
    RESET_MAX_PER_ACCOUNT = int(os.environ.get("RESET_MAX_PER_ACCOUNT", "3"))   # per hour
    MAX_IMAGE_BYTES = 5 * 1024 * 1024

