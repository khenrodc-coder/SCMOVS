-- Phase 4B migration. Run ONCE on a database that was created BEFORE Phase 4B.
-- (Fresh installs already get this column from the updated schema.sql.)
--
--   mysql -u root -p scmovs < database/migrations/001_positions_display_order.sql

USE scmovs;

ALTER TABLE positions
    ADD COLUMN display_order INT UNSIGNED NOT NULL DEFAULT 0 AFTER description;

-- Keep the order the positions already have (President first, and so on)
UPDATE positions SET display_order = id;
