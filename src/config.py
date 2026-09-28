"""Единая конфигурация проекта."""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MODEL_DIR = PROJECT_ROOT / "models"
REPORT_DIR = PROJECT_ROOT / "reports"
FIGURE_DIR = REPORT_DIR / "figures"
DB_PATH = DATA_DIR / "education.db"
MODEL_PATH = MODEL_DIR / "risk_model.joblib"
KNOWLEDGE_INDEX_PATH = MODEL_DIR / "knowledge_tfidf.joblib"
METRICS_PATH = MODEL_DIR / "metrics.json"
MODEL_CARD_PATH = MODEL_DIR / "model_card.md"

RANDOM_SEED = 42
CURRENT_SEMESTER = 8
SNAPSHOT_DATE = "2026-04-30"

FEATURE_COLUMNS = [
    "admission_score",
    "previous_gpa",
    "attendance_rate",
    "late_rate",
    "lms_events_per_course",
    "active_days",
    "avg_session_minutes",
    "submission_on_time_rate",
    "quiz_attempts_per_course",
    "forum_posts_per_course",
    "midterm_avg",
    "assignment_avg",
    "attempts_avg",
    "low_midterm_share",
]

FEATURE_LABELS_RU = {
    "admission_score": "Вступительный балл",
    "previous_gpa": "Средний балл прошлых семестров",
    "attendance_rate": "Доля посещённых занятий",
    "late_rate": "Доля опозданий",
    "lms_events_per_course": "События LMS на дисциплину",
    "active_days": "Активные дни в LMS",
    "avg_session_minutes": "Средняя длительность активности, мин",
    "submission_on_time_rate": "Доля работ, сданных вовремя",
    "quiz_attempts_per_course": "Попытки тестов на дисциплину",
    "forum_posts_per_course": "Сообщения форума на дисциплину",
    "midterm_avg": "Средний балл промежуточного контроля",
    "assignment_avg": "Средний балл заданий",
    "attempts_avg": "Среднее число попыток сдачи",
    "low_midterm_share": "Доля дисциплин с низким промежуточным баллом",
}

RISK_LEVELS = {
    "low": (0.0, 0.35),
    "medium": (0.35, 0.65),
    "high": (0.65, 1.01),
}


def ensure_directories() -> None:
    """Создать каталоги, которые используются конвейером."""
    for path in (RAW_DIR, PROCESSED_DIR, MODEL_DIR, REPORT_DIR, FIGURE_DIR):
        path.mkdir(parents=True, exist_ok=True)
