# SCMOVS enhancement: setup, migration and test notes

## 1. Apply the database migration (existing Windows / MySQL database)
Back up first, then run the migration **once**. Nothing is dropped; `users.full_name` is kept and stays in sync.

```powershell
cd C:\path\to\SCMOVS
mysqldump -u root -p scmovs > backup_before_005.sql
Get-Content database\migrations\005_profiles_names_photos_reset.sql | mysql -u root -p
```
(If `mysql` is not on PATH, use the full path to `mysql.exe`, as in your `.env` `MYSQL_PATH`.)

It adds `users.first_name / middle_name / last_name / photo_path / theme_preference` and the tables
`password_reset_tokens` and `password_reset_requests`. Existing names are split automatically
(students: copied from their student record; others: first word / middle words / last word).
A one-word legacy name gets no last name; the Edit User modal asks for it.

Fresh installs: `database\schema.sql` already includes everything (and I fixed three syntax errors that
stopped it from importing: missing comma in `positions`, duplicate column + trailing comma in `documents`).
`check_project.py` now expects 36 tables.

## 2. Email (password recovery)
1. Copy the new variables from `.env.example` into your `.env` (your `.env` was NOT changed).
2. Gmail: turn on 2-Step Verification, create an App Password at https://myaccount.google.com/apppasswords,
   put it in `MAIL_PASSWORD` (the normal Gmail password will not work).
3. Set `PUBLIC_BASE_URL` to the address people actually open (`http://localhost:5000` for local tests,
   `https://your-domain` in production). Reset links are built from it; the request's Host header is never used.
4. Restart Flask. Until `MAIL_*` and `PUBLIC_BASE_URL` are set, "Forgot Password" answers
   "not available" instead of pretending to send.

## 3. Behaviour you should know about
* **Student IDs:** new students must have exactly 8 digits and the email `<ID>@3holycross.edu.ph`.
  Existing students with old IDs (e.g. `2026-0001`) are untouched and stay editable (any valid email), but
  **they cannot use email password recovery** until their ID/email follow the new format.
* Password-reset requests always get the same generic answer. If SMTP fails for a real account, the visitor
  is not told (that would reveal the account exists); it is written to the audit log (`password_reset_email_failed`).
* Candidate first/middle/last name and department are read-only: they come from the student record
  (type the Student ID and they fill in).
* Candidate photos can be changed on their own until the election closes; this never changes approval.
* Photos are checked by their real file bytes (JPG/PNG/WebP, 5 MB), stored under `uploads/profiles` and
  `uploads/candidates`, and served only to logged-in users. They are not re-encoded (EXIF stays in the file).
* Dark mode exists only for Super Admin (server-enforced). It is a stylesheet override (`static/css/dark.css`).
* Notifications: there was no retention policy in the code, so the bell shows the latest 30. Super/School
  Admins now also receive "Voting opened/closed" notices (de-duplicated), as students already did.
* Every native `<select>` gets icons automatically (`static/js/select_icons.js`); the real select stays in the page.

## 4. Tests
```powershell
# needs a throwaway database named scmovs_test; never point tests at your real data
sh tests/run_all.sh        # (Git Bash / WSL)   Python suites on a freshly rebuilt scmovs_test
cd tests\js; npm i jsdom@24; node modal_ui_test.js   # needs users_modal.html saved beside it (see the file header)
```
