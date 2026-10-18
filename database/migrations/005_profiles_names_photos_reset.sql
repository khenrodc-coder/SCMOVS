-- 005: split names, profile photos, Super Admin theme, password-reset tokens.
-- Run ONCE on an existing database (MySQL 8). Safe for existing data: nothing is dropped,
-- users.full_name is kept (and kept in sync by the app) so every existing query still works.
USE scmovs;
SET NAMES utf8mb4;

ALTER TABLE users
    ADD COLUMN first_name  VARCHAR(60) NULL AFTER full_name,
    ADD COLUMN middle_name VARCHAR(60) NULL AFTER first_name,
    ADD COLUMN last_name   VARCHAR(60) NULL AFTER middle_name,
    ADD COLUMN photo_path  VARCHAR(255) NULL AFTER email,
    ADD COLUMN theme_preference ENUM('light','dark') NOT NULL DEFAULT 'light';

-- Students: copy the exact names already stored on the student record.
UPDATE users u JOIN students s ON s.user_id = u.id
   SET u.first_name = s.first_name, u.middle_name = s.middle_name, u.last_name = s.last_name
 WHERE u.first_name IS NULL;

-- Everyone else: best-effort split of full_name (first word / middle words / last word).
-- A one-word name gets only a first name; the Edit User modal will ask for the missing last name.
UPDATE users
   SET first_name  = SUBSTRING_INDEX(TRIM(full_name), ' ', 1),
       last_name   = IF(LOCATE(' ', TRIM(full_name)) > 0, SUBSTRING_INDEX(TRIM(full_name), ' ', -1), NULL),
       middle_name = IF(LENGTH(TRIM(full_name)) - LENGTH(REPLACE(TRIM(full_name), ' ', '')) >= 2,
                        TRIM(SUBSTRING(TRIM(full_name),
                                       LOCATE(' ', TRIM(full_name)) + 1,
                                       CHAR_LENGTH(TRIM(full_name)) - LOCATE(' ', TRIM(full_name))
                                         - CHAR_LENGTH(SUBSTRING_INDEX(TRIM(full_name), ' ', -1)) - 1)),
                        NULL)
 WHERE first_name IS NULL;

CREATE TABLE password_reset_tokens (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id INT UNSIGNED NOT NULL,
    token_hash CHAR(64) NOT NULL UNIQUE,          -- SHA-256 of the emailed token; the raw token is never stored
    expires_at DATETIME NOT NULL,
    used_at DATETIME NULL,
    requested_ip VARCHAR(45) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_prt_user (user_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE password_reset_requests (          -- every request (any email) so we can rate-limit by IP
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ip_address VARCHAR(45) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_prr_ip (ip_address, created_at)
) ENGINE=InnoDB;
