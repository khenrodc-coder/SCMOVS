-- Phase 4D migration. Run ONCE on a database created BEFORE Phase 4D.
-- (Fresh installs already get this column from the updated schema.sql.)
--
--   mysql -u root -p scmovs < database/migrations/002_backups_checksum.sql

USE scmovs;

ALTER TABLE backups
    ADD COLUMN checksum CHAR(64) NULL AFTER file_size;