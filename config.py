import os
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")

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
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024  # 5 MB

    SYSTEM_NAME = "SCMOVS"
    SYSTEM_FULL_NAME = "Student Council Management and Online Voting System"

    # Backup and recovery (Phase 4D). Backups live OUTSIDE static/ so they are never public.
    BACKUP_FOLDER = os.path.join(BASE_DIR, "backups")
    # Full path if the tools are not on your PATH, e.g. C:\xampp\mysql\bin\mysqldump.exe
    MYSQLDUMP_PATH = os.environ.get("MYSQLDUMP_PATH", "mysqldump")
    MYSQL_PATH = os.environ.get("MYSQL_PATH", "mysql")
