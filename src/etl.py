"""ETL: чтение, очистка, интеграция и загрузка данных в SQLite."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config import DB_PATH, PROCESSED_DIR, PROJECT_ROOT, RAW_DIR, ensure_directories
from src.db import connect


class QualityJournal:
    """Накопитель результатов проверок качества данных."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(self, source: str, check: str, affected: int, action: str) -> None:
        self.rows.append(
            {
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "source_name": source,
                "check_name": check,
                "affected_rows": int(affected),
                "action_taken": action,
            }
        )


def _normalise_group(value: object) -> str:
    text = str(value).upper().strip().replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"^ПИ-?(\d{3})$", r"ПИ-\1", text)
    return text


def _clean_students(raw: pd.DataFrame, journal: QualityJournal) -> pd.DataFrame:
    source = "dean_students.csv"
    before = len(raw)
    raw = raw.drop_duplicates(subset="student_id", keep="last").copy()
    journal.add(source, "Дубликаты student_id", before - len(raw), "Оставлена последняя запись")

    raw["group_name"] = raw["group_name"].map(_normalise_group)
    invalid_groups = ~raw["group_name"].str.match(r"^ПИ-\d{3}$", na=False)
    journal.add(source, "Некорректный код группы", int(invalid_groups.sum()), "Строки отклонены")
    raw = raw.loc[~invalid_groups].copy()

    gender_map = {
        "м": "М", "male": "М", "муж.": "М", "муж": "М",
        "ж": "Ж", "female": "Ж", "жен.": "Ж", "жен": "Ж",
    }
    raw["gender"] = raw["gender"].astype(str).str.strip().str.lower().map(gender_map).fillna("Не указано")

    raw["age"] = pd.to_numeric(raw["age"], errors="coerce")
    invalid_age = raw["age"].isna() | ~raw["age"].between(17, 65)
    journal.add(source, "Пропуск/аномалия возраста", int(invalid_age.sum()), "Замена медианой по группе")
    raw.loc[~raw["age"].between(17, 65), "age"] = np.nan
    raw["age"] = raw["age"].fillna(raw.groupby("group_name")["age"].transform("median"))
    raw["age"] = raw["age"].fillna(raw["age"].median()).round().astype(int)

    raw["admission_score"] = pd.to_numeric(raw["admission_score"], errors="coerce")
    invalid_admission = raw["admission_score"].isna() | ~raw["admission_score"].between(0, 100)
    journal.add(source, "Пропуск/аномалия вступительного балла", int(invalid_admission.sum()), "Замена медианой по группе")
    raw.loc[~raw["admission_score"].between(0, 100), "admission_score"] = np.nan
    raw["admission_score"] = raw["admission_score"].fillna(raw.groupby("group_name")["admission_score"].transform("median"))
    raw["admission_score"] = raw["admission_score"].fillna(raw["admission_score"].median()).round(1)

    raw["previous_gpa"] = pd.to_numeric(raw["previous_gpa"], errors="coerce").clip(2, 5)
    gpa_missing = int(raw["previous_gpa"].isna().sum())
    raw["previous_gpa"] = raw["previous_gpa"].fillna(raw["previous_gpa"].median())
    journal.add(source, "Пропуск среднего балла", gpa_missing, "Замена общей медианой")

    scholarship_map = {"да": 1, "yes": 1, "1": 1, "нет": 0, "no": 0, "0": 0}
    raw["scholarship"] = raw["scholarship"].astype(str).str.strip().str.lower().map(scholarship_map).fillna(0).astype(int)
    raw["full_name"] = raw["full_name"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    return raw[["student_id", "full_name", "group_name", "gender", "age", "admission_score", "previous_gpa", "scholarship"]]


def _clean_courses(raw: pd.DataFrame, journal: QualityJournal) -> pd.DataFrame:
    source = "dean_courses.csv"
    before = len(raw)
    raw = raw.drop_duplicates(subset="course_code", keep="last").copy()
    journal.add(source, "Дубликаты course_code", before - len(raw), "Оставлена последняя запись")
    raw["credits"] = pd.to_numeric(raw["credits"], errors="coerce")
    invalid = raw["course_code"].isna() | raw["course_name"].isna() | raw["credits"].isna() | (raw["credits"] <= 0)
    journal.add(source, "Неполные справочные записи", int(invalid.sum()), "Строки отклонены")
    return raw.loc[~invalid, ["course_code", "course_name", "credits"]].copy()


def _clean_grades(raw: pd.DataFrame, valid_students: set[str], valid_courses: set[str], journal: QualityJournal) -> pd.DataFrame:
    source = "dean_grades.csv"
    raw = raw.copy()
    raw["exported_at"] = pd.to_datetime(raw["exported_at"], errors="coerce", utc=True)
    raw = raw.sort_values("exported_at")
    before = len(raw)
    raw = raw.drop_duplicates(subset=["student_id", "course_code", "semester"], keep="last")
    journal.add(source, "Версионные дубликаты ведомости", before - len(raw), "Выбрана наиболее свежая выгрузка")

    orphan = ~raw["student_id"].isin(valid_students) | ~raw["course_code"].isin(valid_courses)
    journal.add(source, "Нарушение ссылочной целостности", int(orphan.sum()), "Строки отклонены")
    raw = raw.loc[~orphan].copy()
    numeric = ["semester", "midterm_score", "assignment_score", "final_score", "final_grade", "attempt_count"]
    for col in numeric:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    invalid = (
        raw[["semester", "midterm_score", "assignment_score", "final_score", "final_grade", "attempt_count"]].isna().any(axis=1)
        | ~raw["midterm_score"].between(0, 100)
        | ~raw["assignment_score"].between(0, 100)
        | ~raw["final_score"].between(0, 100)
        | ~raw["final_grade"].between(2, 5)
        | ~raw["attempt_count"].between(1, 10)
    )
    journal.add(source, "Неполная/некорректная оценка", int(invalid.sum()), "Строки отклонены")
    raw = raw.loc[~invalid].copy()
    raw[["semester", "final_grade", "attempt_count"]] = raw[["semester", "final_grade", "attempt_count"]].astype(int)
    return raw[["student_id", "course_code", "semester", "midterm_score", "assignment_score", "final_score", "final_grade", "attempt_count"]]


def _clean_attendance(raw: pd.DataFrame, valid_students: set[str], valid_courses: set[str], journal: QualityJournal) -> pd.DataFrame:
    source = "access_attendance.csv"
    raw = raw.copy()
    before = len(raw)
    raw = raw.drop_duplicates(subset=["student_id", "course_code", "lesson_date"], keep="last")
    journal.add(source, "Дубликаты отметок", before - len(raw), "Оставлена последняя отметка")

    value = raw["status"].astype(str).str.strip().str.lower()
    present_values = {"present", "присутствовал", "1", "+"}
    late_values = {"late", "опоздал", "l"}
    absent_values = {"absent", "отсутствовал", "0", "-"}
    known = value.isin(present_values | late_values | absent_values)
    orphan = ~raw["student_id"].isin(valid_students) | ~raw["course_code"].isin(valid_courses)
    invalid_date = pd.to_datetime(raw["lesson_date"], errors="coerce").isna()
    rejected = ~known | orphan | invalid_date
    journal.add(source, "Неизвестный статус/ключ/дата", int(rejected.sum()), "Строки отклонены")
    raw = raw.loc[~rejected].copy()
    value = value.loc[~rejected]
    raw["present"] = value.isin(present_values | late_values).astype(int)
    raw["late"] = value.isin(late_values).astype(int)
    return raw[["student_id", "course_code", "lesson_date", "present", "late"]]


def _clean_lms(raw: pd.DataFrame, valid_students: set[str], valid_courses: set[str], journal: QualityJournal) -> pd.DataFrame:
    source = "lms_events.jsonl"
    raw = raw.copy()
    before = len(raw)
    raw = raw.drop_duplicates(subset="event_id", keep="first")
    journal.add(source, "Дубликаты event_id", before - len(raw), "Оставлено первое событие")

    valid_event_types = {"login", "resource_view", "quiz_attempt", "assignment_submit", "forum_post"}
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], errors="coerce", utc=True)
    raw["duration_minutes"] = pd.to_numeric(raw["duration_minutes"], errors="coerce")
    bad_duration = raw["duration_minutes"].isna() | ~raw["duration_minutes"].between(0, 120)
    journal.add(source, "Пропуск/аномалия длительности", int(bad_duration.sum()), "Замена медианой по типу события")
    raw.loc[~raw["duration_minutes"].between(0, 120), "duration_minutes"] = np.nan
    raw["duration_minutes"] = raw["duration_minutes"].fillna(raw.groupby("event_type")["duration_minutes"].transform("median"))
    raw["duration_minutes"] = raw["duration_minutes"].fillna(raw["duration_minutes"].median()).clip(0, 120).round(2)

    invalid = (
        ~raw["student_id"].isin(valid_students)
        | ~raw["course_code"].isin(valid_courses)
        | ~raw["event_type"].isin(valid_event_types)
        | raw["timestamp"].isna()
    )
    journal.add(source, "Невалидный ключ/тип/время", int(invalid.sum()), "Строки отклонены")
    raw = raw.loc[~invalid].copy()
    raw["event_ts"] = raw["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    raw["on_time"] = raw["on_time"].map({True: 1, False: 0, "true": 1, "false": 0})
    return raw[["event_id", "student_id", "course_code", "event_ts", "event_type", "duration_minutes", "on_time"]]


def run_etl(raw_dir: Path = RAW_DIR, db_path: Path = DB_PATH) -> dict[str, Any]:
    """Выполнить полный ETL и создать нормализованную базу SQLite."""
    ensure_directories()
    required = ["dean_students.csv", "dean_courses.csv", "dean_grades.csv", "access_attendance.csv", "lms_events.jsonl"]
    missing = [name for name in required if not (raw_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"Не найдены сырые источники: {', '.join(missing)}. Сначала запустите generate_data.")

    journal = QualityJournal()
    students = _clean_students(pd.read_csv(raw_dir / "dean_students.csv", encoding="utf-8-sig"), journal)
    courses = _clean_courses(pd.read_csv(raw_dir / "dean_courses.csv", encoding="utf-8-sig"), journal)
    student_ids = set(students["student_id"])
    course_ids = set(courses["course_code"])
    grades = _clean_grades(pd.read_csv(raw_dir / "dean_grades.csv", encoding="utf-8-sig"), student_ids, course_ids, journal)
    attendance = _clean_attendance(pd.read_csv(raw_dir / "access_attendance.csv", sep=";", encoding="utf-8-sig"), student_ids, course_ids, journal)
    lms = _clean_lms(pd.read_json(raw_dir / "lms_events.jsonl", lines=True), student_ids, course_ids, journal)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(db_path)
    try:
        schema = (PROJECT_ROOT / "src" / "schema.sql").read_text(encoding="utf-8")
        connection.executescript(schema)

        group_names = sorted(students["group_name"].unique())
        groups = pd.DataFrame({"group_name": group_names})
        groups["program_code"] = "09.03.03"
        groups["program_name"] = "Прикладная информатика"
        groups["study_year"] = 4
        groups.to_sql("student_groups", connection, if_exists="append", index=False)
        group_map = dict(connection.execute("SELECT group_name, group_id FROM student_groups").fetchall())

        students_db = students.copy()
        students_db["group_id"] = students_db["group_name"].map(group_map)
        students_db.drop(columns="group_name").to_sql("students", connection, if_exists="append", index=False)
        courses.to_sql("courses", connection, if_exists="append", index=False)
        grades.to_sql("enrollments", connection, if_exists="append", index=False)
        lms.to_sql("lms_events", connection, if_exists="append", index=False)
        attendance.to_sql("attendance", connection, if_exists="append", index=False)
        pd.DataFrame(journal.rows).to_sql("data_quality_log", connection, if_exists="append", index=False)

        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise sqlite3.IntegrityError(f"Ошибки внешних ключей: {foreign_key_errors[:5]}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": str(db_path.relative_to(PROJECT_ROOT)),
        "loaded_rows": {
            "student_groups": len(group_names),
            "students": len(students),
            "courses": len(courses),
            "enrollments": len(grades),
            "attendance": len(attendance),
            "lms_events": len(lms),
        },
        "quality_issues_detected": int(sum(row["affected_rows"] for row in journal.rows)),
        "quality_checks": len(journal.rows),
        "foreign_key_errors": 0,
    }
    (PROCESSED_DIR / "etl_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(journal.rows).to_csv(PROCESSED_DIR / "data_quality_log.csv", index=False, encoding="utf-8-sig")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="ETL образовательных данных")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    summary = run_etl(args.raw_dir, args.db)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
