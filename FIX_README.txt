SCMOVS FIX PATCH
================
Copy the contents of this SCMOVS folder INTO your project folder (the one that has run.py) and choose
"Replace the files in the destination" when Windows asks. It does not touch .env, run.py, requirements.txt,
.git or your Railway files.

Then, in PowerShell inside your project folder:
    python database/apply_migration_005.py     (adds the new database columns; safe to run again)
    python run.py
Open the site and press Ctrl+F5 once so the browser loads the new JavaScript.
