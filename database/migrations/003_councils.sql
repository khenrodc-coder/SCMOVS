-- Phase 5A migration. Run ONCE on a database created BEFORE Phase 5A.
-- (Fresh installs already get these columns from the updated schema.sql.)
--
--   mysql -u root -p scmovs < database/migrations/003_councils.sql

USE scmovs;

-- How many people can hold a position in one council (President = 1, Representative = several)
ALTER TABLE positions
    ADD COLUMN seats INT UNSIGNED NOT NULL DEFAULT 1 AFTER display_order,
    ADD CONSTRAINT chk_position_seats CHECK (seats BETWEEN 1 AND 20);

UPDATE positions SET seats = 5 WHERE name = 'Representative';

-- When an officer's assignment ended (council history)
ALTER TABLE council_officers
    ADD COLUMN ended_at DATETIME NULL AFTER created_at;