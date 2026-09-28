from __future__ import annotations

import pandas as pd

from src.config import DB_PATH, FEATURE_COLUMNS
from src.db import connect


def test_database_integrity() -> None:
    assert DB_PATH.exists(), "Сначала выполните python scripts/run_pipeline.py"
    connection = connect(DB_PATH, read_only=True)
    try:
        assert connection.execute("SELECT COUNT(*) FROM students").fetchone()[0] >= 100
        assert connection.execute("SELECT COUNT(*) FROM courses").fetchone()[0] >= 2
        assert connection.execute("SELECT COUNT(*) FROM lms_events").fetchone()[0] > 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_model_features_have_no_missing_or_leakage() -> None:
    connection = connect(DB_PATH, read_only=True)
    try:
        frame = pd.read_sql_query("SELECT * FROM student_features", connection)
    finally:
        connection.close()
    assert not frame[FEATURE_COLUMNS].isna().any().any()
    assert set(["final_gpa", "failed_courses"]).isdisjoint(FEATURE_COLUMNS)
    assert frame["at_risk"].nunique() == 2
