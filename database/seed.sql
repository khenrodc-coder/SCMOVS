-- Reference data. Run AFTER schema.sql.
-- Users, students, the sample election, and the sample council are created by
-- database/seed_dev_data.py because passwords must be hashed.

USE scmovs;
SET NAMES utf8mb4;

INSERT INTO roles (name, display_name) VALUES
('super_admin',     'Super Admin'),
('school_admin',    'School Admin'),
('council_officer', 'Council Officer'),
('student',         'Student');

INSERT INTO permissions (code, module, description) VALUES
('users.manage',          'users',         'Create, edit, and deactivate user accounts and assign roles'),
('students.view',         'students',      'View student records'),
('students.manage',       'students',      'Create and edit student records'),
('departments.manage',    'departments',   'Manage departments'),
('school_years.manage',   'school_years',  'Manage school years'),
('positions.manage',      'positions',     'Manage council positions'),
('elections.view',        'elections',     'View elections'),
('elections.manage',      'elections',     'Create, edit, open, and close elections'),
('elections.publish',     'elections',     'Publish verified election results'),
('candidates.manage',     'candidates',    'Register and review candidates'),
('voting.monitor',        'voting',        'View voting participation (never individual choices)'),
('voting.cast',           'voting',        'Cast a ballot in an eligible election'),
('results.verify',        'results',       'Verify election results'),
('results.view_published','results',       'View published election results'),
('councils.manage',       'councils',      'Manage councils and officers'),
('events.submit',         'events',        'Submit event proposals'),
('events.approve',        'events',        'Review and approve event proposals'),
('projects.submit',       'projects',      'Submit project proposals'),
('projects.approve',      'projects',      'Review and approve project proposals'),
('budgets.request',       'finance',       'Request budgets for approved activities'),
('budgets.approve',       'finance',       'Review and approve budgets'),
('expenses.submit',       'finance',       'Submit expenses for approved activities'),
('expenses.approve',      'finance',       'Review and approve expenses'),
('meetings.manage',       'meetings',      'Manage meetings, attendance, and minutes'),
('documents.manage',      'documents',     'Upload and manage council documents'),
('announcements.manage',  'announcements', 'Create and publish announcements'),
('notifications.view',    'notifications', 'View own notifications'),
('concerns.submit',       'concerns',      'Submit concerns and feedback'),
('concerns.manage',       'concerns',      'Review and respond to concerns'),
('surveys.manage',        'surveys',       'Create and manage surveys'),
('surveys.respond',       'surveys',       'Answer surveys'),
('reports.view',          'reports',       'View and export reports'),
('audit.view',            'audit',         'View audit logs'),
('archives.manage',       'archives',      'Archive and restore records'),
('backups.manage',        'backups',       'Create, download, and restore backups'),
('settings.manage',       'settings',      'Change system settings'),
('transparency.view',     'transparency',  'View public transparency information');

-- Super Admin: every permission
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name = 'super_admin';

-- School Admin: school-level management (no user/role, backup, or settings control)
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r
JOIN permissions p ON p.code IN (
    'students.view','students.manage','positions.manage',
    'elections.view','elections.manage','elections.publish',
    'candidates.manage','voting.monitor','results.verify','results.view_published',
    'councils.manage','events.approve','projects.approve',
    'budgets.approve','expenses.approve','announcements.manage',
    'notifications.view','concerns.manage','surveys.manage',
    'reports.view','transparency.view')
WHERE r.name = 'school_admin';

-- Council Officer: council operations (voting.cast still requires a student record)
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r
JOIN permissions p ON p.code IN (
    'events.submit','projects.submit','budgets.request','expenses.submit',
    'meetings.manage','documents.manage','reports.view',
    'notifications.view','voting.cast','results.view_published',
    'concerns.submit','surveys.respond','transparency.view')
WHERE r.name = 'council_officer';

-- Student
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r
JOIN permissions p ON p.code IN (
    'voting.cast','results.view_published','notifications.view',
    'concerns.submit','surveys.respond','transparency.view')
WHERE r.name = 'student';

INSERT INTO departments (name, code) VALUES
('Elementary',  'ELEM'),
('High School', 'HS'),
('College',     'COL');

INSERT INTO school_years (name, start_date, end_date, status) VALUES
('2026-2027', '2026-06-01', '2027-03-31', 'active');

INSERT INTO positions (name, description, display_order, seats) VALUES
('President',                 'Head of the student council',        1, 1),
('Vice President',            'Assists the President',              2, 1),
('Secretary',                 'Keeps council records and minutes',  3, 1),
('Treasurer',                 'Manages council funds',              4, 1),
('Auditor',                   'Audits council finances',            5, 1),
('Public Information Officer','Handles council communications',     6, 1),
('Representative',            'Represents a year level or section', 7, 5);

INSERT INTO system_settings (setting_key, setting_value, category) VALUES
('system_name',              'SCMOVS',                                                   'general'),
('system_full_name',         'Student Council Management and Online Voting System',      'general'),
('school_name',              'Holy Cross College',                                       'general'),
('school_address',           'Sta.Rosa NE., INC.',                                       'general'),
('session_timeout_minutes',  '30',                                                       'security'),
('password_min_length',      '8',                                                        'security'),
('max_failed_logins',        '5',                                                        'security'),
('lockout_minutes',          '15',                                                       'security'),
('election_require_candidate_per_position', 'true',                                      'election'),
('election_block_pending_candidates',       'true',                                      'election'),
('voting_require_confirmation','true',                                                   'election'),
('notifications_enabled',    'true',                                                     'notification');