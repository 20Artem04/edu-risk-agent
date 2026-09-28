"""Формирование признаков раннего предупреждения на уровне студента."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import CURRENT_SEMESTER, DB_PATH, FEATURE_COLUMNS, FEATURE_LABELS_RU, PROCESSED_DIR, ensure_directories
from src.db import connect


def build_features(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Агрегировать признаки и целевую переменную, сохранить их в БД и CSV.

    Признаки используют только сведения, доступные до итоговой аттестации.
    Цель формируется по итоговым оценкам: наличие хотя бы одной
    неудовлетворительной оценки (двойки) по дисциплинам семестра.
    """
    ensure_directories()
    connection = connect(db_path)
    try:
        students = pd.read_sql_query(
            """
            SELECT s.student_id, s.full_name, g.group_name, s.admission_score,
                   s.previous_gpa
            FROM students s
            JOIN student_groups g ON g.group_id = s.group_id
            """,
            connection,
        )
        attendance = pd.read_sql_query(
            """
            SELECT student_id,
                   AVG(present * 1.0) AS attendance_rate,
                   AVG(late * 1.0) AS late_rate
            FROM attendance
            GROUP BY student_id
            """,
            connection,
        )
        lms = pd.read_sql_query(
            """
            SELECT student_id,
                   COUNT(*) AS lms_events,
                   COUNT(DISTINCT substr(event_ts, 1, 10)) AS active_days,
                   AVG(duration_minutes) AS avg_session_minutes,
                   AVG(CASE WHEN event_type = 'assignment_submit' THEN on_time END) AS submission_on_time_rate,
                   SUM(CASE WHEN event_type = 'quiz_attempt' THEN 1 ELSE 0 END) AS quiz_attempts,
                   SUM(CASE WHEN event_type = 'forum_post' THEN 1 ELSE 0 END) AS forum_posts
            FROM lms_events
            GROUP BY student_id
            """,
            connection,
        )
        grades = pd.read_sql_query(
            """
            SELECT student_id,
                   COUNT(*) AS course_count,
                   AVG(midterm_score) AS midterm_avg,
                   AVG(assignment_score) AS assignment_avg,
                   AVG(attempt_count * 1.0) AS attempts_avg,
                   AVG(CASE WHEN midterm_score < 50 THEN 1.0 ELSE 0.0 END) AS low_midterm_share,
                   SUM(CASE WHEN final_grade = 2 THEN 1 ELSE 0 END) AS failed_courses,
                   AVG(final_grade * 1.0) AS final_gpa
            FROM enrollments
            WHERE semester = ?
            GROUP BY student_id
            """,
            connection,
            params=(CURRENT_SEMESTER,),
        )

        frame = students.merge(attendance, on="student_id", how="left").merge(lms, on="student_id", how="left").merge(grades, on="student_id", how="inner")
        frame["lms_events_per_course"] = frame["lms_events"] / frame["course_count"].replace(0, np.nan)
        frame["quiz_attempts_per_course"] = frame["quiz_attempts"] / frame["course_count"].replace(0, np.nan)
        frame["forum_posts_per_course"] = frame["forum_posts"] / frame["course_count"].replace(0, np.nan)
        frame["at_risk"] = (frame["failed_courses"] >= 1).astype(int)
        frame["semester"] = CURRENT_SEMESTER

        for column in FEATURE_COLUMNS:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
            if frame[column].isna().any():
                frame[column] = frame[column].fillna(frame[column].median())
        if frame[FEATURE_COLUMNS].isna().any().any():
            raise ValueError("После импутации в признаках остались пропуски")
        if frame["at_risk"].nunique() != 2:
            raise ValueError("Целевая переменная должна содержать оба класса")

        db_columns = ["student_id", "semester", *FEATURE_COLUMNS, "at_risk", "failed_courses", "final_gpa"]
        connection.execute("DELETE FROM student_features")
        frame[db_columns].to_sql("student_features", connection, if_exists="append", index=False)
        connection.commit()
    finally:
        connection.close()

    output_columns = ["student_id", "full_name", "group_name", "semester", *FEATURE_COLUMNS, "at_risk", "failed_courses", "final_gpa"]
    output = frame[output_columns].sort_values("student_id").reset_index(drop=True)
    output.to_csv(PROCESSED_DIR / "model_dataset.csv", index=False, encoding="utf-8-sig")

    dictionary_rows = []
    for column in FEATURE_COLUMNS:
        dictionary_rows.append(
            {
                "field": column,
                "description_ru": FEATURE_LABELS_RU[column],
                "type": "числовой",
                "stage_available": "до итоговой аттестации",
                "used_by_model": 1,
            }
        )
    dictionary_rows.extend(
        [
            {"field": "at_risk", "description_ru": "Целевой признак академического риска", "type": "бинарный", "stage_available": "после семестра", "used_by_model": 0},
            {"field": "failed_courses", "description_ru": "Число неудовлетворительных итоговых оценок", "type": "целое", "stage_available": "после семестра", "used_by_model": 0},
            {"field": "final_gpa", "description_ru": "Средняя итоговая оценка", "type": "числовой", "stage_available": "после семестра", "used_by_model": 0},
        ]
    )
    pd.DataFrame(dictionary_rows).to_csv(PROCESSED_DIR / "feature_dictionary.csv", index=False, encoding="utf-8-sig")

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rows": len(output),
        "features": len(FEATURE_COLUMNS),
        "positive_class": int(output["at_risk"].sum()),
        "risk_rate": round(float(output["at_risk"].mean()), 4),
        "missing_values": int(output[FEATURE_COLUMNS].isna().sum().sum()),
        "target_rule": "failed_courses >= 1",
        "leakage_columns_excluded": ["final_gpa", "failed_courses", "final_score", "final_grade"],
    }
    (PROCESSED_DIR / "feature_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Подготовка признаков")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    data = build_features(args.db)
    print(f"Подготовлено {len(data)} наблюдений, доля риска: {data['at_risk'].mean():.1%}")


if __name__ == "__main__":
    main()
