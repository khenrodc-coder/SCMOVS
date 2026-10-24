-- Phase 7B migration: election results (calculate, verify, publish).
-- Run ONCE on a database created BEFORE Phase 7B. Fresh installs already have all of this in schema.sql.
--
--   mysql -u root -p scmovs < database/migrations/006_election_results.sql
-- Calculated election results (Phase 7B). A SNAPSHOT taken when an administrator calculates the results,
-- so published numbers can never change afterwards (for example if a candidate is disqualified later).
-- Counted from the votes table only: these tables never touch ballots.
CREATE TABLE election_result_runs (
    election_id INT UNSIGNED PRIMARY KEY,
    calculated_by INT UNSIGNED NOT NULL,
    calculated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    eligible_voters INT UNSIGNED NOT NULL,
    ballots_counted INT UNSIGNED NOT NULL,
    excluded_votes INT UNSIGNED NOT NULL DEFAULT 0,   -- votes for candidates no longer approved at calculation time
    checksum CHAR(64) NOT NULL,                       -- SHA-256 of the snapshot: verify and publish must match it
    FOREIGN KEY (election_id) REFERENCES elections(id),
    FOREIGN KEY (calculated_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE election_results (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    election_id INT UNSIGNED NOT NULL,
    position_id INT UNSIGNED NOT NULL,
    candidate_id INT UNSIGNED NOT NULL,
    vote_count INT UNSIGNED NOT NULL,
    rank_no INT UNSIGNED NOT NULL,
    outcome ENUM('winner','tie','not_elected') NOT NULL,
    FOREIGN KEY (election_id) REFERENCES elections(id),
    FOREIGN KEY (candidate_id, election_id, position_id) REFERENCES candidates(id, election_id, position_id),
    UNIQUE KEY uq_result_candidate (election_id, candidate_id),
    INDEX idx_results_position (election_id, position_id)
) ENGINE=InnoDB;

DELIMITER $$

-- Calculated results can only be written while the election is closed or awaiting verification
CREATE TRIGGER trg_election_results_bi BEFORE INSERT ON election_results
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(30);
    SELECT status INTO v_status FROM elections WHERE id = NEW.election_id;
    IF v_status NOT IN ('closed', 'pending_verification') THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Results can only be written while the election is closed or awaiting verification.';
    END IF;
END$$

-- A calculated result row is never edited: recalculate instead (delete and insert)
CREATE TRIGGER trg_election_results_bu BEFORE UPDATE ON election_results
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Calculated results cannot be edited. Recalculate the results instead.';
END$$

-- Results of a verified or published election cannot be deleted
CREATE TRIGGER trg_election_results_bd BEFORE DELETE ON election_results
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(30);
    SELECT status INTO v_status FROM elections WHERE id = OLD.election_id;
    IF v_status NOT IN ('closed', 'pending_verification') THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Results of a verified or published election cannot be deleted.';
    END IF;
END$$

-- An election cannot be verified or published without calculated results, a verifier and a publisher
CREATE TRIGGER trg_elections_bu BEFORE UPDATE ON elections
FOR EACH ROW
BEGIN
    IF NEW.status IN ('verified', 'published') AND (NEW.verified_by IS NULL OR NEW.verified_at IS NULL) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Results must be verified before they can be published.';
    END IF;
    IF NEW.status = 'published' AND (NEW.published_by IS NULL OR NEW.published_at IS NULL) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Published results need a publisher and a publication time.';
    END IF;
    IF NEW.status IN ('pending_verification', 'verified', 'published')
       AND NOT EXISTS (SELECT 1 FROM election_result_runs WHERE election_id = NEW.id) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'The results have not been calculated yet.';
    END IF;
END$$

DELIMITER ;
