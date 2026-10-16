-- Phase 7A hardening (Option A): ballot secrecy in backups.
-- Run ONCE on a database created BEFORE this change. Fresh installs get the column from schema.sql.
--
--   mysql -u root -p scmovs < database/migrations/005_backup_ballot_protection.sql

USE scmovs;

-- 1 = this backup was made WITHOUT the ballots and votes tables (and was checked to be free of them).
-- 0 = made before ballot protection: it still contains ballots and votes, which together reveal who
--     voted for whom, so the app will not let it be downloaded or restored.
ALTER TABLE backups
    ADD COLUMN ballots_excluded TINYINT(1) NOT NULL DEFAULT 0 AFTER checksum;