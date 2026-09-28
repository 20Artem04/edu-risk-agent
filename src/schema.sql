PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS query_logs;
DROP TABLE IF EXISTS predictions;
DROP TABLE IF EXISTS model_runs;
DROP TABLE IF EXISTS student_features;
DROP TABLE IF EXISTS attendance;
DROP TABLE IF EXISTS lms_events;
DROP TABLE IF EXISTS enrollments;
DROP TABLE IF EXISTS courses;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS student_groups;
DROP TABLE IF EXISTS data_quality_log;

CREATE TABLE student_groups (
    group_id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name TEXT NOT NULL UNIQUE,
    program_code TEXT NOT NULL DEFAULT '09.03.03',
    program_name TEXT NOT NULL DEFAULT 'Прикладная информатика',
    study_year INTEGER NOT NULL DEFAULT 4
);

CREATE TABLE students (
    student_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    group_id INTEGER NOT NULL,
    gender TEXT CHECK (gender IN ('М', 'Ж', 'Не указано')),
    age INTEGER CHECK (age BETWEEN 17 AND 65),
    admission_score REAL CHECK (admission_score BETWEEN 0 AND 100),
    previous_gpa REAL CHECK (previous_gpa BETWEEN 2 AND 5),
    scholarship INTEGER NOT NULL DEFAULT 0 CHECK (scholarship IN (0, 1)),
    FOREIGN KEY (group_id) REFERENCES student_groups(group_id)
);

CREATE TABLE courses (
    course_code TEXT PRIMARY KEY,
    course_name TEXT NOT NULL,
    credits INTEGER NOT NULL CHECK (credits > 0)
);

CREATE TABLE enrollments (
    enrollment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    course_code TEXT NOT NULL,
    semester INTEGER NOT NULL,
    midterm_score REAL CHECK (midterm_score BETWEEN 0 AND 100),
    assignment_score REAL CHECK (assignment_score BETWEEN 0 AND 100),
    final_score REAL CHECK (final_score BETWEEN 0 AND 100),
    final_grade INTEGER CHECK (final_grade BETWEEN 2 AND 5),
    attempt_count INTEGER CHECK (attempt_count BETWEEN 1 AND 10),
    UNIQUE (student_id, course_code, semester),
    FOREIGN KEY (student_id) REFERENCES students(student_id),
    FOREIGN KEY (course_code) REFERENCES courses(course_code)
);

CREATE TABLE lms_events (
    event_id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    course_code TEXT NOT NULL,
    event_ts TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('login', 'resource_view', 'quiz_attempt', 'assignment_submit', 'forum_post')),
    duration_minutes REAL NOT NULL CHECK (duration_minutes BETWEEN 0 AND 120),
    on_time INTEGER CHECK (on_time IN (0, 1) OR on_time IS NULL),
    FOREIGN KEY (student_id) REFERENCES students(student_id),
    FOREIGN KEY (course_code) REFERENCES courses(course_code)
);

CREATE TABLE attendance (
    attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    course_code TEXT NOT NULL,
    lesson_date TEXT NOT NULL,
    present INTEGER NOT NULL CHECK (present IN (0, 1)),
    late INTEGER NOT NULL DEFAULT 0 CHECK (late IN (0, 1)),
    UNIQUE (student_id, course_code, lesson_date),
    FOREIGN KEY (student_id) REFERENCES students(student_id),
    FOREIGN KEY (course_code) REFERENCES courses(course_code)
);

CREATE TABLE student_features (
    student_id TEXT PRIMARY KEY,
    semester INTEGER NOT NULL,
    admission_score REAL NOT NULL,
    previous_gpa REAL NOT NULL,
    attendance_rate REAL NOT NULL,
    late_rate REAL NOT NULL,
    lms_events_per_course REAL NOT NULL,
    active_days REAL NOT NULL,
    avg_session_minutes REAL NOT NULL,
    submission_on_time_rate REAL NOT NULL,
    quiz_attempts_per_course REAL NOT NULL,
    forum_posts_per_course REAL NOT NULL,
    midterm_avg REAL NOT NULL,
    assignment_avg REAL NOT NULL,
    attempts_avg REAL NOT NULL,
    low_midterm_share REAL NOT NULL,
    at_risk INTEGER NOT NULL CHECK (at_risk IN (0, 1)),
    failed_courses INTEGER NOT NULL,
    final_gpa REAL NOT NULL,
    FOREIGN KEY (student_id) REFERENCES students(student_id)
);

CREATE TABLE model_runs (
    model_run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    threshold REAL NOT NULL,
    test_f1 REAL,
    test_roc_auc REAL,
    test_recall REAL,
    dataset_rows INTEGER NOT NULL,
    artifact_path TEXT NOT NULL
);

CREATE TABLE predictions (
    prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    model_run_id TEXT NOT NULL,
    risk_probability REAL NOT NULL CHECK (risk_probability BETWEEN 0 AND 1),
    predicted_at_risk INTEGER NOT NULL CHECK (predicted_at_risk IN (0, 1)),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('Низкий', 'Средний', 'Высокий')),
    top_factors TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (student_id, model_run_id),
    FOREIGN KEY (student_id) REFERENCES students(student_id),
    FOREIGN KEY (model_run_id) REFERENCES model_runs(model_run_id)
);

CREATE TABLE query_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    session_id TEXT,
    user_role TEXT NOT NULL,
    intent TEXT,
    query_text TEXT,
    response_time_ms REAL,
    result_count INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    llm_used INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE data_quality_log (
    check_id INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at TEXT NOT NULL,
    source_name TEXT NOT NULL,
    check_name TEXT NOT NULL,
    affected_rows INTEGER NOT NULL,
    action_taken TEXT NOT NULL
);

CREATE INDEX idx_students_group ON students(group_id);
CREATE INDEX idx_enrollments_student ON enrollments(student_id);
CREATE INDEX idx_enrollments_course ON enrollments(course_code);
CREATE INDEX idx_lms_student_ts ON lms_events(student_id, event_ts);
CREATE INDEX idx_attendance_student ON attendance(student_id);
CREATE INDEX idx_predictions_student ON predictions(student_id);
CREATE INDEX idx_predictions_risk ON predictions(risk_probability DESC);
CREATE INDEX idx_query_logs_created ON query_logs(created_at DESC);
