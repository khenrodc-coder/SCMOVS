
from pathlib import Path
import re
import sys

backup = Path.home() / "Downloads" / "scmovs_full_backup.sql"

if not backup.is_file():
    sys.exit(f"Backup not found: {backup}")

sql = backup.read_text(encoding="utf-8", errors="replace")

print("Backup:", backup)
print("Size:", f"{backup.stat().st_size:,}", "bytes")

checks = {
    "CREATE TABLE": r"\bCREATE\s+TABLE\b",
    "INSERT INTO": r"\bINSERT\s+INTO\b",
    "CREATE VIEW": r"\bCREATE\b[\s\S]{0,200}?\bVIEW\b",
    "DROP TABLE": r"\bDROP\s+TABLE\b",
    "Foreign key constraints": r"\bFOREIGN KEY\b",
    "Triggers": r"\bCREATE\s+TRIGGER\b",
    "Procedures": r"\bCREATE\s+PROCEDURE\b",
    "Delimiter directives": r"^\s*DELIMITER\b",
}

for label, pattern in checks.items():
    print(f"{label}: {len(re.findall(pattern, sql, re.I))}")

print("\nTable names found:")
names = sorted(set(re.findall(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`([^`]+)`",
    sql,
    re.I,
)))
for name in names:
    print("-", name)

print("\nValidation only: no database changes were made.")
