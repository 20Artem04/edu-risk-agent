"""Генерация воспроизводимых синтетических выгрузок из трёх систем.

Источники имитируют:
1) деканат/электронную ведомость (CSV);
2) LMS (JSON Lines);
3) систему контроля доступа (CSV с разделителем ';').

В данные намеренно добавлены пропуски, дубликаты и разные варианты кодирования
категорий, чтобы ETL выполнял реальную очистку, а не простое копирование.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import CURRENT_SEMESTER, RANDOM_SEED, RAW_DIR, ensure_directories

MALE_FIRST = ["Александр", "Максим", "Иван", "Артём", "Дмитрий", "Никита", "Михаил", "Егор", "Кирилл", "Роман", "Даниил", "Андрей"]
FEMALE_FIRST = ["Анна", "Мария", "София", "Елена", "Дарья", "Алина", "Полина", "Виктория", "Екатерина", "Ксения", "Анастасия", "Валерия"]
MALE_LAST = ["Иванов", "Петров", "Смирнов", "Кузнецов", "Попов", "Соколов", "Лебедев", "Козлов", "Новиков", "Морозов", "Волков", "Фёдоров", "Алексеев", "Орлов"]
FEMALE_LAST = ["Иванова", "Петрова", "Смирнова", "Кузнецова", "Попова", "Соколова", "Лебедева", "Козлова", "Новикова", "Морозова", "Волкова", "Фёдорова", "Алексеева", "Орлова"]
PATRONYMIC_M = ["Александрович", "Иванович", "Сергеевич", "Дмитриевич", "Андреевич", "Михайлович"]
PATRONYMIC_F = ["Александровна", "Ивановна", "Сергеевна", "Дмитриевна", "Андреевна", "Михайловна"]

COURSES = [
    ("UD-801", "Управление данными", 5, 0.68),
    ("ML-802", "Машинное обучение", 5, 0.84),
    ("IS-803", "Проектирование информационных систем", 4, 0.58),
    ("BI-804", "Бизнес-аналитика", 4, 0.63),
    ("PM-805", "Управление ИТ-проектами", 3, 0.44),
    ("EC-806", "Электив: интеллектуальные агенты", 3, 0.55),
]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + np.exp(-x))


def _grade(score: float) -> int:
    if score < 50:
        return 2
    if score < 70:
        return 3
    if score < 85:
        return 4
    return 5


def _dirty_group(value: str, rng: np.random.Generator) -> str:
    variants = [value, value.lower(), f" {value} ", value.replace("-", " – "), value.replace("ПИ", "пи")]
    return str(rng.choice(variants, p=[0.72, 0.08, 0.08, 0.05, 0.07]))


def generate_raw_data(n_students: int = 420, seed: int = RANDOM_SEED, output_dir: Path = RAW_DIR) -> dict[str, int]:
    """Сформировать все сырые источники и вернуть число строк в каждом."""
    ensure_directories()
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    n_groups = 7
    groups = [f"ПИ-40{i + 1}" for i in range(n_groups)]
    students: list[dict] = []
    latent: dict[str, tuple[float, float]] = {}

    for i in range(n_students):
        sid = f"STU{i + 1:04d}"
        female = bool(rng.integers(0, 2))
        first = str(rng.choice(FEMALE_FIRST if female else MALE_FIRST))
        last = str(rng.choice(FEMALE_LAST if female else MALE_LAST))
        patronymic = str(rng.choice(PATRONYMIC_F if female else PATRONYMIC_M))
        ability = float(rng.normal(0, 0.95))
        diligence = float(0.25 * ability + rng.normal(0, 0.95))
        previous_gpa = float(np.clip(3.55 + 0.52 * ability + 0.26 * diligence + rng.normal(0, 0.22), 2.0, 5.0))
        admission = float(np.clip(69 + 11.5 * ability + rng.normal(0, 7), 35, 100))
        age = int(np.clip(round(rng.normal(21.8, 1.05)), 19, 29))
        gender = str(rng.choice(["Ж", "ж", "female", "жен."], p=[0.65, 0.1, 0.1, 0.15])) if female else str(rng.choice(["М", "м", "male", "муж."], p=[0.65, 0.1, 0.1, 0.15]))
        group = groups[i % n_groups]
        students.append(
            {
                "student_id": sid,
                "full_name": f"{last} {first} {patronymic}",
                "group_name": _dirty_group(group, rng),
                "gender": gender,
                "age": age,
                "admission_score": round(admission, 1),
                "previous_gpa": round(previous_gpa, 2),
                "scholarship": str(rng.choice(["да", "нет", "yes", "no"], p=[0.35, 0.45, 0.1, 0.1])) if previous_gpa >= 3.8 else str(rng.choice(["нет", "no"], p=[0.85, 0.15])),
                "registry_updated_at": "2026-02-01T09:00:00+03:00",
            }
        )
        latent[sid] = (ability, diligence)

    student_df = pd.DataFrame(students)
    # Контролируемые дефекты качества.
    missing_age_idx = rng.choice(student_df.index, size=max(2, n_students // 50), replace=False)
    student_df.loc[missing_age_idx, "age"] = np.nan
    missing_adm_idx = rng.choice(student_df.index, size=max(2, n_students // 70), replace=False)
    student_df.loc[missing_adm_idx, "admission_score"] = np.nan
    student_df.loc[int(rng.integers(0, n_students)), "age"] = 130
    student_df.loc[int(rng.integers(0, n_students)), "admission_score"] = 155
    duplicated_students = student_df.sample(6, random_state=seed)
    student_export = pd.concat([student_df, duplicated_students], ignore_index=True)
    student_export.to_csv(output_dir / "dean_students.csv", index=False, encoding="utf-8-sig")

    courses_df = pd.DataFrame(COURSES, columns=["course_code", "course_name", "credits", "difficulty"])
    courses_df.drop(columns=["difficulty"]).to_csv(output_dir / "dean_courses.csv", index=False, encoding="utf-8-sig")

    grades: list[dict] = []
    attendance_rows: list[dict] = []
    lms_rows: list[dict] = []
    lesson_start = date(2026, 2, 9)
    event_start = datetime(2026, 2, 1, 8, 0, tzinfo=timezone(timedelta(hours=3)))

    for student in students:
        sid = student["student_id"]
        ability, diligence = latent[sid]
        prev = float(student["previous_gpa"])
        for course_code, _course_name, _credits, difficulty in COURSES:
            engagement = float(_sigmoid(0.95 * diligence + 0.28 * ability - 0.55 * difficulty + rng.normal(0, 0.48)))
            attendance_prob = float(np.clip(0.48 + 0.48 * engagement + 0.07 * ability - 0.05 * difficulty, 0.2, 0.99))
            present_count = 0
            late_count = 0
            for week in range(12):
                lesson_date = lesson_start + timedelta(days=7 * week + int(rng.choice([0, 1, 2, 3])))
                draw = float(rng.random())
                if draw < attendance_prob * 0.12:
                    status = str(rng.choice(["late", "опоздал", "L"]))
                    present_count += 1
                    late_count += 1
                elif draw < attendance_prob:
                    status = str(rng.choice(["present", "присутствовал", "1", "+"]))
                    present_count += 1
                else:
                    status = str(rng.choice(["absent", "отсутствовал", "0", "-"]))
                attendance_rows.append({"student_id": sid, "course_code": course_code, "lesson_date": lesson_date.isoformat(), "status": status})

            attendance_rate = present_count / 12
            midterm = float(np.clip(60 + 17 * ability + 25 * engagement - 11 * difficulty + rng.normal(0, 9), 0, 100))
            assignment = float(np.clip(64 + 13 * ability + 29 * engagement - 8 * difficulty + rng.normal(0, 8), 0, 100))
            score = float(np.clip(0.38 * midterm + 0.34 * assignment + 0.18 * attendance_rate * 100 + 0.10 * ((prev - 2) / 3 * 100) + 3 + rng.normal(0, 6), 0, 100))
            final_grade = _grade(score)
            attempts = int(np.clip(1 + (midterm < 55) + (assignment < 55) + rng.binomial(1, max(0.0, 0.28 - engagement * 0.2)), 1, 4))
            grades.append(
                {
                    "student_id": sid,
                    "course_code": course_code,
                    "semester": CURRENT_SEMESTER,
                    "midterm_score": round(midterm, 1),
                    "assignment_score": round(assignment, 1),
                    "final_score": round(score, 1),
                    "final_grade": final_grade,
                    "attempt_count": attempts,
                    "exported_at": "2026-06-25T18:00:00+03:00",
                }
            )

            # Активность LMS до итоговой аттестации.
            n_events = int(np.clip(rng.poisson(7 + 25 * engagement), 3, 55))
            event_types = ["login", "resource_view", "quiz_attempt", "assignment_submit", "forum_post"]
            probs = np.array([0.18, 0.42, 0.18, 0.16, 0.06])
            for _ in range(n_events):
                event_type = str(rng.choice(event_types, p=probs))
                day_offset = int(rng.integers(0, 88))
                minute_offset = int(rng.integers(0, 13 * 60))
                ts = event_start + timedelta(days=day_offset, minutes=minute_offset)
                base_duration = {"login": 2, "resource_view": 13, "quiz_attempt": 18, "assignment_submit": 8, "forum_post": 11}[event_type]
                duration = float(np.clip(rng.gamma(2.1, base_duration / 2.1) * (0.75 + 0.5 * engagement), 0.5, 120))
                on_time = None
                if event_type == "assignment_submit":
                    on_time = bool(rng.random() < np.clip(0.36 + 0.60 * engagement, 0.1, 0.99))
                lms_rows.append(
                    {
                        "event_id": f"EVT{len(lms_rows) + 1:07d}",
                        "student_id": sid,
                        "course_code": course_code,
                        "timestamp": ts.isoformat(),
                        "event_type": event_type,
                        "duration_minutes": round(duration, 2),
                        "on_time": on_time,
                    }
                )

    grades_df = pd.DataFrame(grades)
    # Старые версии части ведомости: ETL должен сохранить наиболее свежую запись.
    old_rows = grades_df.sample(80, random_state=seed).copy()
    old_rows["exported_at"] = "2026-06-20T12:00:00+03:00"
    old_rows["midterm_score"] = (old_rows["midterm_score"] - rng.uniform(0, 8, len(old_rows))).clip(0)
    old_rows["final_grade"] = np.nan
    grades_export = pd.concat([grades_df, old_rows], ignore_index=True).sample(frac=1, random_state=seed)
    grades_export.to_csv(output_dir / "dean_grades.csv", index=False, encoding="utf-8-sig")

    attendance_df = pd.DataFrame(attendance_rows)
    attendance_export = pd.concat([attendance_df, attendance_df.sample(120, random_state=seed)], ignore_index=True)
    bad_status_idx = rng.choice(attendance_export.index, size=12, replace=False)
    attendance_export.loc[bad_status_idx, "status"] = "?"
    attendance_export.to_csv(output_dir / "access_attendance.csv", index=False, sep=";", encoding="utf-8-sig")

    lms_df = pd.DataFrame(lms_rows)
    bad_duration_idx = rng.choice(lms_df.index, size=40, replace=False)
    lms_df.loc[bad_duration_idx[:20], "duration_minutes"] = -5
    lms_df.loc[bad_duration_idx[20:], "duration_minutes"] = np.nan
    lms_export = pd.concat([lms_df, lms_df.sample(100, random_state=seed)], ignore_index=True)
    with (output_dir / "lms_events.jsonl").open("w", encoding="utf-8") as fh:
        for record in lms_export.to_dict(orient="records"):
            # NaN в JSON заменяем на null.
            clean_record = {key: (None if pd.isna(value) else value) for key, value in record.items()}
            fh.write(json.dumps(clean_record, ensure_ascii=False) + "\n")

    metadata = {
        "generator": "src.generate_data",
        "seed": seed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "synthetic": True,
        "n_students_requested": n_students,
        "sources": {
            "dean_students.csv": len(student_export),
            "dean_courses.csv": len(courses_df),
            "dean_grades.csv": len(grades_export),
            "access_attendance.csv": len(attendance_export),
            "lms_events.jsonl": len(lms_export),
        },
    }
    (output_dir / "generation_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata["sources"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Генератор синтетических образовательных данных")
    parser.add_argument("--students", type=int, default=420, help="Число студентов")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED, help="Seed генератора")
    args = parser.parse_args()
    counts = generate_raw_data(args.students, args.seed)
    print("Синтетические источники сформированы:")
    for name, count in counts.items():
        print(f"  {name}: {count:,} строк")


if __name__ == "__main__":
    main()
