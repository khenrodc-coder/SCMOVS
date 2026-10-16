"""Database backup and recovery with mysqldump / mysql.

Safety rules used here:
- The tools are started WITHOUT a shell, with a list of arguments (no command injection).
- The database password is never put on the command line: it goes into a temporary
  option file that only this program can read, deleted right after the tool finishes.
- File names come from the database and are checked against a strict pattern, never from the browser.
- Every backup gets a SHA-256 checksum. BALLOT SECRECY (Phase 7A, option A): the `ballots` table says WHO voted and the `votes` table says WHAT
was chosen. Together they reveal how each student voted, so a downloadable backup must never hold both.
  * Backups are made WITHOUT those two tables (mysqldump --ignore-table), and every new file is scanned
    to prove it. A file that fails the scan is deleted.
  * Because a restore therefore never touches ballots/votes, a restore is refused when the voting data
    refers to candidates, elections or students created AFTER the backup (their ids could be reused and
    old votes would silently count for the wrong person).
  * Backups made before this rule contain ballot data: they can no longer be downloaded or restored here.
Only COUNTS are read from these tables in this module, and never with the two tables joined together.
"""
import hashlib
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime

from flask import current_app

from app.audit.services import log_action
from app.db import close_db, fetch_all, fetch_one, get_db
from app.utils import get_page

PER_PAGE = 10
NAME_RE = re.compile(r"^scmovs_\d{8}_\d{6}_[0-9a-f]{6}\.sql$")
PROTECTED_TABLES = ("ballots", "votes")      # never part of a backup file
# any statement in a dump that creates, fills or locks one of the protected tables
PROTECTED_RE = re.compile(rb"(?:INSERT INTO|CREATE TABLE|LOCK TABLES|DROP TABLE IF EXISTS|ALTER TABLE)\s+`(?:"
                          + b"|".join(t.encode() for t in PROTECTED_TABLES) + rb")`", re.IGNORECASE)
DUMP_TIMEOUT = 300           # seconds
RESTORE_TIMEOUT = 900


# ============================================================ helpers

def backup_folder():
    path = current_app.config["BACKUP_FOLDER"]
    os.makedirs(path, exist_ok=True)
    return path


def backup_path(filename):
    """Full path of a backup file. Refuses any name that does not match our own pattern."""
    if not NAME_RE.match(filename):
        raise ValueError("Invalid backup file name.")
    return os.path.join(backup_folder(), filename)


def tool_status():
    """Are mysqldump and mysql available? Shown on the page so setup problems are obvious."""
    cfg = current_app.config
    return [{"name": name, "setting": setting, "found": shutil.which(cfg[setting]) is not None}
            for name, setting in (("mysqldump", "MYSQLDUMP_PATH"), ("mysql", "MYSQL_PATH"))]


def _quote(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@contextmanager
def _credentials_file():
    """A temporary option file with the DB login (permissions: owner only). Always deleted afterwards."""
    cfg = current_app.config
    fd, path = tempfile.mkstemp(prefix="scmovs_", suffix=".cnf")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("[client]\n")
            handle.write(f"user={_quote(cfg['DATABASE_USER'])}\n")
            handle.write(f"password={_quote(cfg['DATABASE_PASSWORD'])}\n")
        yield path
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _connection_args(tool_setting, option_file):
    cfg = current_app.config
    # --defaults-extra-file must be the first option
    return [cfg[tool_setting], f"--defaults-extra-file={option_file}",
            f"--host={cfg['DATABASE_HOST']}", f"--port={cfg['DATABASE_PORT']}", "--default-character-set=utf8mb4"]


def _clean_error(text):
    """Short, safe version of a tool's error output (never contains the password)."""
    password = current_app.config["DATABASE_PASSWORD"]
    lines = [ln for ln in (text or "").splitlines(
    ) if ln.strip() and "Using a password" not in ln]
    message = " ".join(lines)
    if password:
        message = message.replace(password, "***")
    return message[:250]


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _has_completion_marker(path):
    """mysqldump writes '-- Dump completed' as the last comment of a finished dump."""
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        handle.seek(max(0, handle.tell() - 400))
        return b"-- Dump completed" in handle.read()


def file_contains_protected_data(path):
    """True if the dump creates, fills or locks the ballots/votes tables. Reads the file in blocks."""
    overlap = b""
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            if PROTECTED_RE.search(overlap + block):
                return True
            # a statement may start at the end of one block
            overlap = block[-100:]
    return False


def protection_problem(backup):
    """Message when this backup is not protected (made before ballot protection), else None."""
    if not backup.get("ballots_excluded"):
        return ("This backup was made before ballot protection and still contains ballot data, so it cannot be "
                "downloaded or restored here. Create a new backup. (Delete the old file from the backups "
                "folder if you no longer need it.)")
    return None


def voting_data_conflict(backup):
    """Message when restoring this backup could break links between ballots and the records they refer to.

    ballots/votes are not in the backup, so a restore leaves them alone. That is only safe if every candidate,
    election and student they point to already existed when the backup was made. Counts only, and the two
    tables are never joined to each other.
    """
    created = backup["created_at"]
    checks = (
        ("candidate(s) with votes", "SELECT COUNT(DISTINCT c.id) AS n FROM votes v "
                                    "JOIN candidates c ON c.id = v.candidate_id WHERE c.created_at > %s"),
        ("election(s) with ballots", "SELECT COUNT(DISTINCT e.id) AS n FROM ballots b "
                                     "JOIN elections e ON e.id = b.election_id WHERE e.created_at > %s"),
        ("voter(s) (students)", "SELECT COUNT(DISTINCT s.id) AS n FROM ballots b "
                                "JOIN students s ON s.id = b.student_id WHERE s.created_at > %s"),
    )
    found = []
    for label, sql in checks:
        count = fetch_one(sql, (created,))["n"]
        if count:
            found.append(f"{count} {label}")
    if not found:
        return None
    detail = ", ".join(found)
    return ("This backup is too old to restore safely: the voting data refers to records created after it "
            f"({detail}). Restoring would break the link between ballots and the records they refer to. "
            "Use a newer backup.")


def orphaned_voting_references():
    """How many ballots/votes point at a record that no longer exists. Should always be 0."""
    queries = ("SELECT COUNT(*) AS n FROM votes v LEFT JOIN candidates c ON c.id = v.candidate_id WHERE c.id IS NULL",
               "SELECT COUNT(*) AS n FROM votes v LEFT JOIN elections e ON e.id = v.election_id WHERE e.id IS NULL",
               "SELECT COUNT(*) AS n FROM ballots b LEFT JOIN students s ON s.id = b.student_id WHERE s.id IS NULL",
               "SELECT COUNT(*) AS n FROM ballots b LEFT JOIN elections e ON e.id = b.election_id WHERE e.id IS NULL")
    return sum(fetch_one(sql)["n"] for sql in queries)


def verify_backup_file(backup):
    """Return an error message if the stored file is missing, changed or incomplete, else None."""
    if backup["status"] != "completed":
        return "Only completed backups can be used."
    problem = protection_problem(backup)
    if problem:
        return problem
    try:
        path = backup_path(backup["filename"])
    except ValueError:
        return "The backup record has an invalid file name."
    if not os.path.isfile(path):
        return "The backup file is missing from the backups folder."
    if not backup["checksum"]:
        return "This backup has no checksum, so it cannot be trusted."
    if os.path.getsize(path) != backup["file_size"] or _sha256(path) != backup["checksum"]:
        return "The backup file was changed after it was created. It will not be used."
    return None


# =========================================================== listing

def list_backups(args):
    total = fetch_one("SELECT COUNT(*) AS n FROM backups")["n"]
    page, pages = get_page(args, total, PER_PAGE)
    rows = fetch_all(
        "SELECT b.id, b.filename, b.file_size, b.status, b.note, b.created_at, b.completed_at, u.full_name AS created_by_name "
        "FROM backups b LEFT JOIN users u ON u.id = b.created_by ORDER BY b.id DESC LIMIT %s OFFSET %s",
        (PER_PAGE, (page - 1) * PER_PAGE))
    return {"backups": rows, "page": page, "pages": pages, "total": total}


def get_backup(backup_id):
    return fetch_one("SELECT id, filename, file_size, checksum, ballots_excluded, status, note, created_at FROM backups WHERE id = %s",
                     (backup_id,))


# ================================================================ create

def create_backup(actor_id, note=""):
    """Make a full backup WITHOUT the ballots and votes tables. Returns (backup_id, error_or_None)."""
    filename = f"scmovs_{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(3)}.sql"
    path = backup_path(filename)

    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO backups (filename, status, note, created_by) VALUES (%s, 'in_progress', %s, %s)",
                   (filename, note or None, actor_id))
    backup_id = cursor.lastrowid
    db.commit()
    cursor.close()

    error = None
    try:
        with _credentials_file() as option_file:
            args = _connection_args("MYSQLDUMP_PATH", option_file) + [
                "--single-transaction", "--routines", "--triggers"] + [
                f"--ignore-table={current_app.config['DATABASE_NAME']}.{table}" for table in PROTECTED_TABLES] + [
                f"--result-file={path}", current_app.config["DATABASE_NAME"]]
            proc = subprocess.run(args, capture_output=True,
                                  text=True, timeout=DUMP_TIMEOUT)
        if proc.returncode != 0:
            error = _clean_error(proc.stderr) or "mysqldump failed."
        elif not os.path.isfile(path) or not _has_completion_marker(path):
            error = "The backup file looks incomplete."
        elif file_contains_protected_data(path):
            # Should never happen. If it does, the file is deleted below: it must not be downloadable.
            error = "The backup contained ballot data, so it was discarded to protect ballot secrecy."
    except FileNotFoundError:
        error = "mysqldump was not found. Install the MySQL command-line tools or set MYSQLDUMP_PATH in .env."
    except subprocess.TimeoutExpired:
        error = "The backup took too long and was stopped."
    except OSError as problem:
        error = f"Could not run mysqldump: {problem.strerror}"

    cursor = db.cursor()
    try:
        if error:
            if os.path.isfile(path):
                os.remove(path)
            cursor.execute("UPDATE backups SET status = 'failed', note = %s, completed_at = NOW() WHERE id = %s",
                           (error[:255], backup_id))
            log_action(actor_id, "backup_failed", "backups", f"Backup {filename} failed: {error}"[:500],
                       affected_record=f"backup:{backup_id}", commit=False)
        else:
            cursor.execute("UPDATE backups SET status = 'completed', file_size = %s, checksum = %s, "
                           "ballots_excluded = 1, completed_at = NOW() WHERE id = %s",
                           (os.path.getsize(path), _sha256(path), backup_id))
            log_action(actor_id, "backup_created", "backups",
                       f"Created backup {filename} (ballots and votes excluded for ballot secrecy)",
                       affected_record=f"backup:{backup_id}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
    return backup_id, error


# =============================================================== restore

def restore_backup(backup, actor):
    """Replace the database with the contents of a backup. Returns an error message or None.

    Order of work: verify the file -> refuse during voting -> automatic safety backup of the
    CURRENT data -> run the restore -> re-register backup records that the restore overwrote.
    """
    problem = verify_backup_file(backup)
    if problem:
        return problem
    if fetch_one("SELECT COUNT(*) AS n FROM elections WHERE status = 'open'")["n"]:
        return "An election is open. Close it before restoring a backup, so no votes are lost."
    conflict = voting_data_conflict(backup)
    if conflict:
        return conflict
    safety_id, error = create_backup(
        actor["id"], f"Automatic backup before restoring {backup['filename']}")
    if error:
        return "The safety backup failed, so nothing was restored. " + error
    safety = get_backup(safety_id)

    # The restore replaces the backups table too, so remember the current records first
    snapshot = fetch_all("SELECT filename, file_size, checksum, ballots_excluded, status, note, created_by, "
                         "created_at, completed_at FROM backups")

    # IMPORTANT: end this request's own database transaction first. An open transaction keeps
    # locks on the tables it read, and the restore must DROP and re-create those same tables.
    close_db()

    failure = None
    try:
        with _credentials_file() as option_file, open(backup_path(backup["filename"]), "rb") as sql_file:
            args = _connection_args(
                "MYSQL_PATH", option_file) + [current_app.config["DATABASE_NAME"]]
            proc = subprocess.run(
                args, stdin=sql_file, capture_output=True, text=True, timeout=RESTORE_TIMEOUT)
        if proc.returncode != 0:
            failure = _clean_error(
                proc.stderr) or "The mysql tool reported an error."
    except FileNotFoundError:
        failure = "The mysql tool was not found. Set MYSQL_PATH in .env."
    except subprocess.TimeoutExpired:
        failure = "The restore took too long and was stopped."
    except OSError as problem:
        failure = f"Could not run the mysql tool: {problem.strerror}"

    # the tables were replaced: start from a fresh connection
    close_db()
    try:
        _reconcile_after_restore(
            snapshot, actor, backup["filename"], safety["filename"], failure)
    except Exception:
        if not failure:
            raise
    if failure:
        return (f"The restore did not finish ({failure}). The database may be partly restored. "
                f"Your data from before the attempt is saved in {safety['filename']}.")
    return None


def _user_exists(user_id):
    return fetch_one("SELECT id FROM users WHERE id = %s", (user_id,)) is not None


def _reconcile_after_restore(snapshot, actor, restored_name, safety_name, failure):
    """Put back / repair the backup records the restore overwrote, and write the audit entry."""
    present = {row["filename"]
               for row in fetch_all("SELECT filename FROM backups")}
    fallback = fetch_one("SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id "
                         "WHERE r.name = 'super_admin' ORDER BY u.id LIMIT 1")
    db = get_db()
    cursor = db.cursor()
    try:
        for row in snapshot:
            if row["filename"] in present:
                # The restored copy of this record may be older (a backup's own record is saved
                # as "in progress" just before the dump runs), so bring it up to date.
                cursor.execute("UPDATE backups SET file_size = %s, checksum = %s, ballots_excluded = %s, status = %s, "
                               "note = %s, completed_at = %s WHERE filename = %s",
                               (row["file_size"], row["checksum"], row["ballots_excluded"], row["status"], row["note"],
                                row["completed_at"], row["filename"]))
                continue
            owner = row["created_by"] if _user_exists(
                row["created_by"]) else (fallback["id"] if fallback else None)
            if owner is None:
                continue
        cursor.execute(
            "INSERT INTO backups (filename, file_size, checksum, ballots_excluded, status, note, created_by, "
            "created_at, completed_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (row["filename"], row["file_size"], row["checksum"], row["ballots_excluded"], row["status"], row["note"], owner,
             row["created_at"], row["completed_at"]))
        outcome = "FAILED" if failure else "completed"
        orphans = orphaned_voting_references()
        warning = f" WARNING: {orphans} ballot/vote record(s) now point at missing records." if orphans else ""
        log_action(actor["id"] if _user_exists(actor["id"]) else None, "backup_restore_failed" if failure else "backup_restored",
                   "backups", f"Restore from {restored_name} {outcome} by {actor['username']}. "
                   f"Safety backup of the previous data: {safety_name}.{warning}"[:500], commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
