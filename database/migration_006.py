"""Shared definition of migration 006 (used by apply_migration_006.py and by the tests)."""

USER_COLUMNS = [
    ("barangay", "VARCHAR(80) NULL"),
    ("purok_street", "VARCHAR(120) NULL"),
    ("city_municipality", "VARCHAR(60) NULL"),
    ("province", "VARCHAR(40) NOT NULL DEFAULT 'Nueva Ecija'"),
    ("birthdate", "DATE NULL"),
    ("contact_number", "VARCHAR(20) NULL"),
]

# Super Admin can vote: a ballot belongs EITHER to a student OR to a Super Admin account.
BALLOT_ALTER = (
    "ALTER TABLE ballots "
    "MODIFY student_id INT UNSIGNED NULL, "
    "ADD COLUMN voter_user_id INT UNSIGNED NULL AFTER student_id, "
    "ADD CONSTRAINT fk_ballots_voter FOREIGN KEY (voter_user_id) REFERENCES users(id), "
    "ADD UNIQUE KEY uq_ballot_voter_election (voter_user_id, election_id), "
    "ADD CONSTRAINT chk_ballot_one_voter CHECK ((student_id IS NULL) <> (voter_user_id IS NULL))"
)

BALLOT_TRIGGER = """CREATE TRIGGER trg_ballots_bi BEFORE INSERT ON ballots
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(30);
    DECLARE v_start DATETIME;
    DECLARE v_end DATETIME;
    DECLARE v_election_dept INT UNSIGNED;
    DECLARE v_student_dept INT UNSIGNED;
    DECLARE v_student_status VARCHAR(20);
    DECLARE v_role VARCHAR(30);
    DECLARE v_active TINYINT(1);

    SELECT status, start_at, end_at, department_id
      INTO v_status, v_start, v_end, v_election_dept
      FROM elections WHERE id = NEW.election_id;

    IF v_status <> 'open' OR NOW() < v_start OR NOW() > v_end THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Election is not open for voting.';
    END IF;

    IF NEW.student_id IS NOT NULL THEN
        SELECT department_id, status INTO v_student_dept, v_student_status FROM students WHERE id = NEW.student_id;
        IF v_student_dept <> v_election_dept THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Student does not belong to the election department.';
        END IF;
        IF v_student_status <> 'active' THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only active students can vote.';
        END IF;
    ELSE
        SELECT r.name, u.is_active INTO v_role, v_active
          FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = NEW.voter_user_id;
        IF v_role IS NULL OR v_role <> 'super_admin' OR v_active <> 1 THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only an active Super Admin can vote without a student record.';
        END IF;
    END IF;
END"""

PARTICIPATION_VIEW = """CREATE OR REPLACE VIEW v_election_participation AS
SELECT
    e.id AS election_id,
    (SELECT COUNT(*) FROM students s
      WHERE s.department_id = e.department_id
        AND s.school_year_id = e.school_year_id
        AND s.status = 'active')
    + (SELECT COUNT(*) FROM users u JOIN roles r ON r.id = u.role_id
        WHERE r.name = 'super_admin' AND u.is_active = 1) AS eligible_voters,
    (SELECT COUNT(*) FROM ballots b WHERE b.election_id = e.id) AS votes_cast
FROM elections e
"""
