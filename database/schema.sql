-- SCMOVS schema. Requires MySQL 8.0.16 or newer (CHECK constraints are enforced).
-- Run on an empty database named scmovs.

USE scmovs;
SET NAMES utf8mb4;

-- =====================================================
-- ACCESS CONTROL
-- =====================================================

CREATE TABLE roles (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(30) NOT NULL UNIQUE,
    display_name VARCHAR(60) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE permissions (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(60) NOT NULL UNIQUE,
    module VARCHAR(40) NOT NULL,
    description VARCHAR(255) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE role_permissions (
    role_id INT UNSIGNED NOT NULL,
    permission_id INT UNSIGNED NOT NULL,
    PRIMARY KEY (role_id, permission_id),
    FOREIGN KEY (role_id) REFERENCES roles(id),
    FOREIGN KEY (permission_id) REFERENCES permissions(id)
) ENGINE=InnoDB;

CREATE TABLE users (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,      -- students log in with their student number
    email VARCHAR(120) NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(120) NOT NULL,
    first_name VARCHAR(60) NULL,
    middle_name VARCHAR(60) NULL,
    last_name VARCHAR(60) NULL,
    photo_path VARCHAR(255) NULL,
    theme_preference ENUM('light','dark') NOT NULL DEFAULT 'light',
    barangay VARCHAR(80) NULL,
    purok_street VARCHAR(120) NULL,
    city_municipality VARCHAR(60) NULL,
    province VARCHAR(40) NOT NULL DEFAULT 'Nueva Ecija',
    birthdate DATE NULL,
    contact_number VARCHAR(20) NULL,
    role_id INT UNSIGNED NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    must_change_password TINYINT(1) NOT NULL DEFAULT 0,
    failed_login_attempts INT UNSIGNED NOT NULL DEFAULT 0,
    locked_until DATETIME NULL,
    last_login_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (role_id) REFERENCES roles(id),
    INDEX idx_users_role (role_id),
    INDEX idx_users_active (is_active)
) ENGINE=InnoDB;

-- =====================================================
-- ACADEMIC STRUCTURE
-- =====================================================

CREATE TABLE departments (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(60) NOT NULL UNIQUE,
    code VARCHAR(10) NOT NULL UNIQUE,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE school_years (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(20) NOT NULL UNIQUE,          -- e.g. 2026-2027
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status ENUM('upcoming','active','closed','archived') NOT NULL DEFAULT 'upcoming',
    -- Generated column: 1 when active, NULL otherwise. UNIQUE allows many NULLs,
    -- so the database guarantees at most ONE active school year.
    active_flag TINYINT GENERATED ALWAYS AS (CASE WHEN status = 'active' THEN 1 ELSE NULL END) STORED,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_school_years_one_active (active_flag),
    CONSTRAINT chk_school_year_dates CHECK (end_date > start_date)
) ENGINE=InnoDB;

CREATE TABLE students (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id INT UNSIGNED NOT NULL UNIQUE,
    student_number VARCHAR(30) NOT NULL UNIQUE,   -- official Student ID
    first_name VARCHAR(60) NOT NULL,
    middle_name VARCHAR(60) NULL,
    last_name VARCHAR(60) NOT NULL,
    department_id INT UNSIGNED NOT NULL,
    year_level VARCHAR(20) NOT NULL,
    section VARCHAR(30) NOT NULL,
    school_year_id INT UNSIGNED NOT NULL,
    status ENUM('active','inactive','graduated','archived') NOT NULL DEFAULT 'active',
    created_by INT UNSIGNED NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (department_id) REFERENCES departments(id),
    FOREIGN KEY (school_year_id) REFERENCES school_years(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    INDEX idx_students_department (department_id),
    INDEX idx_students_school_year (school_year_id),
    INDEX idx_students_status (status),
    INDEX idx_students_name (last_name, first_name)
) ENGINE=InnoDB;

CREATE TABLE positions (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(80) NOT NULL UNIQUE,
    description VARCHAR(255) NULL,
    display_order INT UNSIGNED NOT NULL DEFAULT 0,
    seats INT UNSIGNED NOT NULL DEFAULT 1,           -- how many people hold this position per council (Phase 5A)   -- default ballot order (Phase 4B)
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_position_seats CHECK (seats BETWEEN 1 AND 20)
) ENGINE=InnoDB;

-- =====================================================
-- ELECTIONS, CANDIDATES, BALLOTS
-- =====================================================

CREATE TABLE elections (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    department_id INT UNSIGNED NOT NULL,
    school_year_id INT UNSIGNED NOT NULL,
    start_at DATETIME NOT NULL,
    end_at DATETIME NOT NULL,
    status ENUM('draft','scheduled','open','closed','pending_verification',
                'verified','published','archived') NOT NULL DEFAULT 'draft',
    created_by INT UNSIGNED NOT NULL,
    verified_by INT UNSIGNED NULL,
    verified_at DATETIME NULL,
    published_by INT UNSIGNED NULL,
    published_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (department_id) REFERENCES departments(id),
    FOREIGN KEY (school_year_id) REFERENCES school_years(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (verified_by) REFERENCES users(id),
    FOREIGN KEY (published_by) REFERENCES users(id),
    INDEX idx_elections_dept_status (department_id, status),
    INDEX idx_elections_school_year (school_year_id),
    INDEX idx_elections_dates (start_at, end_at),
    CONSTRAINT chk_election_dates CHECK (end_at > start_at)
) ENGINE=InnoDB;

CREATE TABLE election_positions (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    election_id INT UNSIGNED NOT NULL,
    position_id INT UNSIGNED NOT NULL,
    display_order INT UNSIGNED NOT NULL DEFAULT 1,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    FOREIGN KEY (election_id) REFERENCES elections(id),
    FOREIGN KEY (position_id) REFERENCES positions(id),
    UNIQUE KEY uq_election_position (election_id, position_id)
) ENGINE=InnoDB;

CREATE TABLE candidates (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    election_id INT UNSIGNED NOT NULL,
    student_id INT UNSIGNED NOT NULL,
    position_id INT UNSIGNED NOT NULL,
    platform TEXT NULL,
    photo_path VARCHAR(255) NULL,
    status ENUM('pending','approved','rejected','disqualified') NOT NULL DEFAULT 'pending',
    remarks VARCHAR(500) NULL,
    reviewed_by INT UNSIGNED NULL,
    reviewed_at DATETIME NULL,
    created_by INT UNSIGNED NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    -- The position must be one of this election's positions
    FOREIGN KEY (election_id, position_id) REFERENCES election_positions(election_id, position_id),
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (reviewed_by) REFERENCES users(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    UNIQUE KEY uq_candidate_student_election (election_id, student_id),
    UNIQUE KEY uq_candidate_scope (id, election_id, position_id),   -- target for votes FK
    INDEX idx_candidates_student (student_id),
    INDEX idx_candidates_status (status)
) ENGINE=InnoDB;

CREATE TABLE ballots (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    election_id INT UNSIGNED NOT NULL,
    student_id INT UNSIGNED NULL,                 -- a student's ballot ...
    voter_user_id INT UNSIGNED NULL,              -- ... or a Super Admin's ballot (exactly one of the two)
    submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status ENUM('submitted') NOT NULL DEFAULT 'submitted',
    FOREIGN KEY (election_id) REFERENCES elections(id),
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (voter_user_id) REFERENCES users(id),
    CONSTRAINT chk_ballot_one_voter CHECK ((student_id IS NULL) <> (voter_user_id IS NULL)),
    UNIQUE KEY uq_ballot_voter_election (voter_user_id, election_id),
    -- Duplicate-vote prevention at database level
    UNIQUE KEY uq_ballot_student_election (student_id, election_id),
    UNIQUE KEY uq_ballot_scope (id, election_id),                   -- target for votes FK
    INDEX idx_ballots_election (election_id)
) ENGINE=InnoDB;

CREATE TABLE votes (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ballot_id INT UNSIGNED NOT NULL,
    election_id INT UNSIGNED NOT NULL,
    position_id INT UNSIGNED NOT NULL,
    candidate_id INT UNSIGNED NOT NULL,
    -- The ballot and the candidate must belong to the SAME election,
    -- and the candidate must be running for the SAME position.
    FOREIGN KEY (ballot_id, election_id) REFERENCES ballots(id, election_id),
    FOREIGN KEY (candidate_id, election_id, position_id) REFERENCES candidates(id, election_id, position_id),
    -- One choice per position per ballot
    UNIQUE KEY uq_vote_ballot_position (ballot_id, position_id),
    INDEX idx_votes_tally (election_id, position_id, candidate_id)
) ENGINE=InnoDB;

-- =====================================================
-- COUNCILS
-- =====================================================

CREATE TABLE councils (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    department_id INT UNSIGNED NOT NULL,
    school_year_id INT UNSIGNED NOT NULL,
    election_id INT UNSIGNED NULL,
    term_start DATE NOT NULL,
    term_end DATE NOT NULL,
    status ENUM('active','completed','archived') NOT NULL DEFAULT 'active',
    created_by INT UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (department_id) REFERENCES departments(id),
    FOREIGN KEY (school_year_id) REFERENCES school_years(id),
    FOREIGN KEY (election_id) REFERENCES elections(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    INDEX idx_councils_dept_year (department_id, school_year_id),
    INDEX idx_councils_status (status),
    CONSTRAINT chk_council_dates CHECK (term_end > term_start)
) ENGINE=InnoDB;

CREATE TABLE council_officers (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    council_id INT UNSIGNED NOT NULL,
    user_id INT UNSIGNED NOT NULL,
    student_id INT UNSIGNED NULL,
    position_id INT UNSIGNED NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at DATETIME NULL,                      -- when the assignment ended (Phase 5A)
    FOREIGN KEY (council_id) REFERENCES councils(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (position_id) REFERENCES positions(id),
    UNIQUE KEY uq_officer_council_user (council_id, user_id),
    INDEX idx_officers_user (user_id)
) ENGINE=InnoDB;

-- =====================================================
-- EVENTS AND PROJECTS
-- =====================================================

CREATE TABLE events (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    council_id INT UNSIGNED NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    objectives TEXT NOT NULL,
    location VARCHAR(200) NOT NULL,
    event_start DATETIME NOT NULL,
    event_end DATETIME NOT NULL,
    supporting_info TEXT NULL,
    status ENUM('draft','submitted','under_review','approved','rejected','completed')
        NOT NULL DEFAULT 'draft',
    submitted_by INT UNSIGNED NOT NULL,
    submitted_at DATETIME NULL,
    reviewed_by INT UNSIGNED NULL,
    reviewed_at DATETIME NULL,
    review_remarks VARCHAR(500) NULL,
    is_archived TINYINT(1) NOT NULL DEFAULT 0,
    archived_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (council_id) REFERENCES councils(id),
    FOREIGN KEY (submitted_by) REFERENCES users(id),
    FOREIGN KEY (reviewed_by) REFERENCES users(id),
    INDEX idx_events_council (council_id),
    INDEX idx_events_status (status),
    INDEX idx_events_start (event_start),
    CONSTRAINT chk_event_dates CHECK (event_end >= event_start),
    -- Nobody approves their own proposal
    CONSTRAINT chk_event_no_self_review CHECK (reviewed_by IS NULL OR reviewed_by <> submitted_by)
) ENGINE=InnoDB;

CREATE TABLE projects (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    council_id INT UNSIGNED NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    objectives TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status ENUM('draft','submitted','under_review','approved','rejected','in_progress','completed')
        NOT NULL DEFAULT 'draft',
    completion_report TEXT NULL,
    submitted_by INT UNSIGNED NOT NULL,
    submitted_at DATETIME NULL,
    reviewed_by INT UNSIGNED NULL,
    reviewed_at DATETIME NULL,
    review_remarks VARCHAR(500) NULL,
    is_archived TINYINT(1) NOT NULL DEFAULT 0,
    archived_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (council_id) REFERENCES councils(id),
    FOREIGN KEY (submitted_by) REFERENCES users(id),
    FOREIGN KEY (reviewed_by) REFERENCES users(id),
    INDEX idx_projects_council (council_id),
    INDEX idx_projects_status (status),
    CONSTRAINT chk_project_dates CHECK (end_date >= start_date),
    CONSTRAINT chk_project_no_self_review CHECK (reviewed_by IS NULL OR reviewed_by <> submitted_by)
) ENGINE=InnoDB;

-- =====================================================
-- MEETINGS AND DOCUMENTS
-- =====================================================

CREATE TABLE meetings (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    council_id INT UNSIGNED NOT NULL,
    title VARCHAR(200) NOT NULL,
    meeting_at DATETIME NOT NULL,
    location VARCHAR(200) NOT NULL,
    agenda TEXT NULL,
    status ENUM('scheduled','completed','cancelled') NOT NULL DEFAULT 'scheduled',
    created_by INT UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (council_id) REFERENCES councils(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    INDEX idx_meetings_council_date (council_id, meeting_at)
) ENGINE=InnoDB;

CREATE TABLE meeting_attendance (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    meeting_id INT UNSIGNED NOT NULL,
    officer_id INT UNSIGNED NOT NULL,
    attendance ENUM('present','absent','excused') NOT NULL,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id),
    FOREIGN KEY (officer_id) REFERENCES council_officers(id),
    UNIQUE KEY uq_attendance (meeting_id, officer_id)
) ENGINE=InnoDB;

CREATE TABLE meeting_minutes (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    meeting_id INT UNSIGNED NOT NULL UNIQUE,
    content TEXT NOT NULL,
    recorded_by INT UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id),
    FOREIGN KEY (recorded_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE documents (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description VARCHAR(500) NULL,
    category ENUM('report','minutes','proposal','financial','memo','other') NOT NULL DEFAULT 'other',  
    original_filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255) NOT NULL UNIQUE,   -- generated safe name inside uploads/
    mime_type VARCHAR(100) NOT NULL,
    file_size INT UNSIGNED NOT NULL,
    visibility ENUM('private','public') NOT NULL DEFAULT 'private',
    uploaded_by INT UNSIGNED NOT NULL,
    council_id INT UNSIGNED NULL,
    event_id INT UNSIGNED NULL,
    project_id INT UNSIGNED NULL,
    meeting_id INT UNSIGNED NULL,
    is_archived TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (uploaded_by) REFERENCES users(id),
    FOREIGN KEY (council_id) REFERENCES councils(id),
    FOREIGN KEY (event_id) REFERENCES events(id),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (meeting_id) REFERENCES meetings(id),
    INDEX idx_documents_council (council_id),
    INDEX idx_documents_library (council_id, is_archived, category)
) ENGINE=InnoDB;

-- =====================================================
-- FINANCE
-- =====================================================

CREATE TABLE budgets (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id INT UNSIGNED NULL,
    project_id INT UNSIGNED NULL,
    requested_amount DECIMAL(12,2) NOT NULL,
    approved_amount DECIMAL(12,2) NULL,
    breakdown TEXT NOT NULL,
    description TEXT NOT NULL,
    supporting_document_id INT UNSIGNED NULL,
    status ENUM('draft','submitted','under_review','approved','rejected') NOT NULL DEFAULT 'draft',
    requested_by INT UNSIGNED NOT NULL,
    submitted_at DATETIME NULL,
    reviewed_by INT UNSIGNED NULL,
    reviewed_at DATETIME NULL,
    review_remarks VARCHAR(500) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (event_id) REFERENCES events(id),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (supporting_document_id) REFERENCES documents(id),
    FOREIGN KEY (requested_by) REFERENCES users(id),
    FOREIGN KEY (reviewed_by) REFERENCES users(id),
    INDEX idx_budgets_event (event_id),
    INDEX idx_budgets_project (project_id),
    INDEX idx_budgets_status (status),
    -- Exactly one of event_id / project_id
    CONSTRAINT chk_budget_one_activity CHECK ((event_id IS NULL) <> (project_id IS NULL)),
    CONSTRAINT chk_budget_requested CHECK (requested_amount > 0),
    CONSTRAINT chk_budget_approved_range CHECK (approved_amount IS NULL
        OR (approved_amount >= 0 AND approved_amount <= requested_amount)),
    CONSTRAINT chk_budget_approved_has_amount CHECK (status <> 'approved' OR approved_amount IS NOT NULL),
    CONSTRAINT chk_budget_no_self_review CHECK (reviewed_by IS NULL OR reviewed_by <> requested_by)
) ENGINE=InnoDB;

CREATE TABLE expenses (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_id INT UNSIGNED NULL,
    project_id INT UNSIGNED NULL,
    description VARCHAR(500) NOT NULL,
    amount DECIMAL(12,2) NOT NULL,
    expense_date DATE NOT NULL,
    receipt_document_id INT UNSIGNED NULL,
    status ENUM('draft','submitted','under_review','approved','rejected') NOT NULL DEFAULT 'draft',
    submitted_by INT UNSIGNED NOT NULL,
    submitted_at DATETIME NULL,
    reviewed_by INT UNSIGNED NULL,
    reviewed_at DATETIME NULL,
    review_remarks VARCHAR(500) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (event_id) REFERENCES events(id),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (receipt_document_id) REFERENCES documents(id),
    FOREIGN KEY (submitted_by) REFERENCES users(id),
    FOREIGN KEY (reviewed_by) REFERENCES users(id),
    INDEX idx_expenses_event (event_id),
    INDEX idx_expenses_project (project_id),
    INDEX idx_expenses_status (status),
    INDEX idx_expenses_date (expense_date),
    CONSTRAINT chk_expense_one_activity CHECK ((event_id IS NULL) <> (project_id IS NULL)),
    CONSTRAINT chk_expense_amount CHECK (amount > 0),
    CONSTRAINT chk_expense_no_self_review CHECK (reviewed_by IS NULL OR reviewed_by <> submitted_by)
) ENGINE=InnoDB;

-- =====================================================
-- COMMUNICATION
-- =====================================================

CREATE TABLE announcements (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    author_id INT UNSIGNED NOT NULL,
    target_audience ENUM('all_students','department','council','administrators') NOT NULL,
    department_id INT UNSIGNED NULL,
    status ENUM('draft','published','archived') NOT NULL DEFAULT 'draft',
    publish_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (author_id) REFERENCES users(id),
    FOREIGN KEY (department_id) REFERENCES departments(id),
    INDEX idx_announcements_status (status, publish_at),
    CONSTRAINT chk_announcement_department CHECK (
        (target_audience = 'department' AND department_id IS NOT NULL)
        OR (target_audience <> 'department' AND department_id IS NULL))
) ENGINE=InnoDB;

CREATE TABLE notifications (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id INT UNSIGNED NOT NULL,
    title VARCHAR(150) NOT NULL,
    message VARCHAR(500) NOT NULL,
    related_module VARCHAR(40) NULL,
    link_url VARCHAR(255) NULL,
    is_read TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at DATETIME NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_notifications_user (user_id, is_read, created_at)
) ENGINE=InnoDB;

CREATE TABLE concerns (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    student_id INT UNSIGNED NOT NULL,
    category ENUM('concern','feedback') NOT NULL,
    subject VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    status ENUM('submitted','under_review','in_progress','resolved','closed')
        NOT NULL DEFAULT 'submitted',
    is_private TINYINT(1) NOT NULL DEFAULT 1,   -- private: only the student and authorized staff can see it
    response TEXT NULL,
    responded_by INT UNSIGNED NULL,
    responded_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (responded_by) REFERENCES users(id),
    INDEX idx_concerns_student (student_id),
    INDEX idx_concerns_status (status)
) ENGINE=InnoDB;

CREATE TABLE surveys (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT NULL,
    target_department_id INT UNSIGNED NULL,      -- NULL = all departments
    status ENUM('draft','published','closed','results_published','archived')
        NOT NULL DEFAULT 'draft',
    opens_at DATETIME NULL,
    closes_at DATETIME NULL,
    created_by INT UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (target_department_id) REFERENCES departments(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    INDEX idx_surveys_status (status)
) ENGINE=InnoDB;

CREATE TABLE survey_questions (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    survey_id INT UNSIGNED NOT NULL,
    question_text VARCHAR(500) NOT NULL,
    question_type ENUM('single_choice','text') NOT NULL,
    is_required TINYINT(1) NOT NULL DEFAULT 1,
    display_order INT UNSIGNED NOT NULL DEFAULT 1,
    FOREIGN KEY (survey_id) REFERENCES surveys(id),
    INDEX idx_survey_questions_survey (survey_id, display_order)
) ENGINE=InnoDB;

CREATE TABLE survey_options (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    question_id INT UNSIGNED NOT NULL,
    option_text VARCHAR(255) NOT NULL,
    display_order INT UNSIGNED NOT NULL DEFAULT 1,
    FOREIGN KEY (question_id) REFERENCES survey_questions(id),
    INDEX idx_survey_options_question (question_id, display_order)
) ENGINE=InnoDB;

CREATE TABLE survey_responses (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    survey_id INT UNSIGNED NOT NULL,
    question_id INT UNSIGNED NOT NULL,
    student_id INT UNSIGNED NOT NULL,
    option_id INT UNSIGNED NULL,
    text_answer TEXT NULL,
    submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (survey_id) REFERENCES surveys(id),
    FOREIGN KEY (question_id) REFERENCES survey_questions(id),
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (option_id) REFERENCES survey_options(id),
    UNIQUE KEY uq_response_student_question (student_id, question_id),   -- one answer per question
    INDEX idx_responses_survey (survey_id),
    CONSTRAINT chk_response_has_answer CHECK (option_id IS NOT NULL OR text_answer IS NOT NULL)
) ENGINE=InnoDB;

-- =====================================================
-- ADMINISTRATION
-- =====================================================

CREATE TABLE audit_logs (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id INT UNSIGNED NULL,                   -- NULL for failed logins of unknown users
    action VARCHAR(60) NOT NULL,
    module VARCHAR(40) NOT NULL,
    affected_record VARCHAR(120) NULL,
    description VARCHAR(500) NOT NULL,
    ip_address VARCHAR(45) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_audit_user (user_id),
    INDEX idx_audit_module_action (module, action),
    INDEX idx_audit_created (created_at)
) ENGINE=InnoDB;

CREATE TABLE archives (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    entity_type ENUM('election','school_year','council','event','project','student','other') NOT NULL,
    entity_id INT UNSIGNED NOT NULL,
    reason VARCHAR(255) NULL,
    archived_by INT UNSIGNED NOT NULL,
    archived_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    restored_by INT UNSIGNED NULL,
    restored_at DATETIME NULL,
    FOREIGN KEY (archived_by) REFERENCES users(id),
    FOREIGN KEY (restored_by) REFERENCES users(id),
    INDEX idx_archives_entity (entity_type, entity_id)
) ENGINE=InnoDB;

CREATE TABLE backups (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) NOT NULL UNIQUE,
    file_size BIGINT UNSIGNED NULL,
    checksum CHAR(64) NULL,
    status ENUM('in_progress','completed','failed') NOT NULL DEFAULT 'in_progress',
    note VARCHAR(255) NULL,
    created_by INT UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,
    FOREIGN KEY (created_by) REFERENCES users(id),
    INDEX idx_backups_created (created_at)
) ENGINE=InnoDB;

CREATE TABLE system_settings (
    setting_key VARCHAR(80) NOT NULL PRIMARY KEY,
    setting_value VARCHAR(500) NOT NULL,
    category ENUM('general','academic','election','notification','security') NOT NULL,
    updated_by INT UNSIGNED NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (updated_by) REFERENCES users(id)
) ENGINE=InnoDB;

-- =====================================================
-- PASSWORD RECOVERY (migration 005)
-- =====================================================
CREATE TABLE password_reset_tokens (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id INT UNSIGNED NOT NULL,
    token_hash CHAR(64) NOT NULL UNIQUE,
    expires_at DATETIME NOT NULL,
    used_at DATETIME NULL,
    requested_ip VARCHAR(45) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_prt_user (user_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE password_reset_requests (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ip_address VARCHAR(45) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_prr_ip (ip_address, created_at)
) ENGINE=InnoDB;


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

-- =====================================================
-- VIEWS (aggregate only: they never expose who voted for whom)
-- =====================================================

CREATE VIEW v_election_participation AS
SELECT
    e.id AS election_id,
    (SELECT COUNT(*) FROM students s
      WHERE s.department_id = e.department_id
        AND s.school_year_id = e.school_year_id
        AND s.status = 'active')
    + (SELECT COUNT(*) FROM users u JOIN roles r ON r.id = u.role_id
        WHERE r.name = 'super_admin' AND u.is_active = 1) AS eligible_voters,
    (SELECT COUNT(*) FROM ballots b WHERE b.election_id = e.id) AS votes_cast
FROM elections e;

CREATE VIEW v_election_results AS
SELECT
    c.election_id,
    c.position_id,
    c.id AS candidate_id,
    COUNT(v.id) AS vote_count
FROM candidates c
LEFT JOIN votes v ON v.candidate_id = c.id
WHERE c.status = 'approved'
GROUP BY c.election_id, c.position_id, c.id;

-- =====================================================
-- TRIGGERS (database-level enforcement of critical rules)
-- =====================================================

DELIMITER $$

-- A candidate must belong to the same department as the election
CREATE TRIGGER trg_candidates_bi BEFORE INSERT ON candidates
FOR EACH ROW
BEGIN
    DECLARE v_student_dept INT UNSIGNED;
    DECLARE v_election_dept INT UNSIGNED;
    SELECT department_id INTO v_student_dept FROM students WHERE id = NEW.student_id;
    SELECT department_id INTO v_election_dept FROM elections WHERE id = NEW.election_id;
    IF v_student_dept <> v_election_dept THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Candidate must belong to the election department.';
    END IF;
END$$

-- A ballot is accepted only for an open election, inside its time window,
-- from an active student of the election's department
CREATE TRIGGER trg_ballots_bi BEFORE INSERT ON ballots
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
END$$

-- Only approved candidates can receive votes
CREATE TRIGGER trg_votes_bi BEFORE INSERT ON votes
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(20);
    SELECT status INTO v_status FROM candidates WHERE id = NEW.candidate_id;
    IF v_status <> 'approved' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only approved candidates can receive votes.';
    END IF;
END$$

-- Submitted ballots and votes cannot be changed or deleted
CREATE TRIGGER trg_ballots_bu BEFORE UPDATE ON ballots
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Submitted ballots cannot be modified.';
END$$

CREATE TRIGGER trg_ballots_bd BEFORE DELETE ON ballots
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Submitted ballots cannot be deleted.';
END$$

CREATE TRIGGER trg_votes_bu BEFORE UPDATE ON votes
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Submitted votes cannot be modified.';
END$$

CREATE TRIGGER trg_votes_bd BEFORE DELETE ON votes
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Submitted votes cannot be deleted.';
END$$

-- Audit logs are append-only
CREATE TRIGGER trg_audit_logs_bu BEFORE UPDATE ON audit_logs
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Audit logs cannot be modified.';
END$$

CREATE TRIGGER trg_audit_logs_bd BEFORE DELETE ON audit_logs
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Audit logs cannot be deleted.';
END$$

-- A budget request needs an approved event/project and cannot start as approved
CREATE TRIGGER trg_budgets_bi BEFORE INSERT ON budgets
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(20);
    IF NEW.status NOT IN ('draft','submitted') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A new budget request must start as draft or submitted.';
    END IF;
    IF NEW.event_id IS NOT NULL THEN
        SELECT status INTO v_status FROM events WHERE id = NEW.event_id;
        IF v_status IS NULL OR v_status NOT IN ('approved','completed') THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A budget requires an approved event.';
        END IF;
    ELSE
        SELECT status INTO v_status FROM projects WHERE id = NEW.project_id;
        IF v_status IS NULL OR v_status NOT IN ('approved','in_progress','completed') THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A budget requires an approved project.';
        END IF;
    END IF;
END$$

-- An expense needs an approved event/project and cannot start as approved
CREATE TRIGGER trg_expenses_bi BEFORE INSERT ON expenses
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(20);
    IF NEW.status NOT IN ('draft','submitted') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A new expense must start as draft or submitted.';
    END IF;
    IF NEW.event_id IS NOT NULL THEN
        SELECT status INTO v_status FROM events WHERE id = NEW.event_id;
        IF v_status IS NULL OR v_status NOT IN ('approved','completed') THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'An expense requires an approved event.';
        END IF;
    ELSE
        SELECT status INTO v_status FROM projects WHERE id = NEW.project_id;
        IF v_status IS NULL OR v_status NOT IN ('approved','in_progress','completed') THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'An expense requires an approved project.';
        END IF;
    END IF;
END$$

-- Approving an expense must not exceed: approved budget - already approved expenses
-- (Flask also locks the rows in a transaction so two approvals cannot race.)
CREATE TRIGGER trg_expenses_bu BEFORE UPDATE ON expenses
FOR EACH ROW
BEGIN
    DECLARE v_budget DECIMAL(12,2) DEFAULT 0;
    DECLARE v_spent DECIMAL(12,2) DEFAULT 0;

    IF NEW.status = 'approved' AND OLD.status <> 'approved' THEN
        IF NEW.event_id IS NOT NULL THEN
            SELECT COALESCE(SUM(approved_amount), 0) INTO v_budget
              FROM budgets WHERE event_id = NEW.event_id AND status = 'approved';
            SELECT COALESCE(SUM(amount), 0) INTO v_spent
              FROM expenses WHERE event_id = NEW.event_id AND status = 'approved' AND id <> NEW.id;
        ELSE
            SELECT COALESCE(SUM(approved_amount), 0) INTO v_budget
              FROM budgets WHERE project_id = NEW.project_id AND status = 'approved';
            SELECT COALESCE(SUM(amount), 0) INTO v_spent
              FROM expenses WHERE project_id = NEW.project_id AND status = 'approved' AND id <> NEW.id;
        END IF;
        IF NEW.amount > (v_budget - v_spent) THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Approved expenses cannot exceed the available approved budget.';
        END IF;
    END IF;
END$$

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