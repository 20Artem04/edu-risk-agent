"""Детерминированные инструменты доступа агента к данным.

LLM не имеет прямого доступа к SQL: все запросы параметризованы и собраны здесь.
Это снижает риск SQL-инъекций и позволяет реализовать ролевой контроль.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import DB_PATH, FEATURE_LABELS_RU, METRICS_PATH
from src.db import connect
from src.knowledge import search_knowledge


class AnalyticsTools:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path

    def _latest_run(self, connection) -> str:
        row = connection.execute("SELECT model_run_id FROM model_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:
            raise RuntimeError("Нет обученной модели. Выполните конвейер подготовки.")
        return str(row["model_run_id"])

    def overview(self) -> dict[str, Any]:
        connection = connect(self.db_path, read_only=True)
        try:
            run_id = self._latest_run(connection)
            row = connection.execute(
                """
                SELECT COUNT(*) AS students,
                       SUM(CASE WHEN p.risk_level = 'Высокий' THEN 1 ELSE 0 END) AS high_risk,
                       SUM(CASE WHEN p.risk_level = 'Средний' THEN 1 ELSE 0 END) AS medium_risk,
                       AVG(p.risk_probability) AS avg_probability,
                       AVG(sf.attendance_rate) AS attendance_rate,
                       AVG(sf.midterm_avg) AS midterm_avg
                FROM predictions p
                JOIN student_features sf ON sf.student_id = p.student_id
                WHERE p.model_run_id = ?
                """,
                (run_id,),
            ).fetchone()
            groups = connection.execute("SELECT COUNT(*) AS value FROM student_groups").fetchone()["value"]
            return {
                "model_run_id": run_id,
                "students": int(row["students"] or 0),
                "groups": int(groups),
                "high_risk": int(row["high_risk"] or 0),
                "medium_risk": int(row["medium_risk"] or 0),
                "avg_probability": float(row["avg_probability"] or 0),
                "attendance_rate": float(row["attendance_rate"] or 0),
                "midterm_avg": float(row["midterm_avg"] or 0),
            }
        finally:
            connection.close()

    def student_card(self, student_id: str) -> dict[str, Any] | None:
        connection = connect(self.db_path, read_only=True)
        try:
            run_id = self._latest_run(connection)
            row = connection.execute(
                """
                SELECT s.student_id, s.full_name, g.group_name,
                       p.risk_probability, p.risk_level, p.predicted_at_risk,
                       p.top_factors, sf.previous_gpa, sf.attendance_rate,
                       sf.submission_on_time_rate, sf.midterm_avg,
                       sf.assignment_avg, sf.active_days, sf.failed_courses,
                       sf.final_gpa
                FROM students s
                JOIN student_groups g ON g.group_id = s.group_id
                JOIN predictions p ON p.student_id = s.student_id AND p.model_run_id = ?
                JOIN student_features sf ON sf.student_id = s.student_id
                WHERE s.student_id = ?
                """,
                (run_id, student_id.upper()),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["top_factors"] = json.loads(result["top_factors"])
            return result
        finally:
            connection.close()

    def list_students(self) -> pd.DataFrame:
        connection = connect(self.db_path, read_only=True)
        try:
            return pd.read_sql_query(
                """SELECT s.student_id, s.full_name, g.group_name
                   FROM students s JOIN student_groups g ON g.group_id=s.group_id
                   ORDER BY g.group_name, s.full_name""",
                connection,
            )
        finally:
            connection.close()

    def group_summary(self, group_name: str) -> dict[str, Any] | None:
        connection = connect(self.db_path, read_only=True)
        try:
            run_id = self._latest_run(connection)
            row = connection.execute(
                """
                SELECT g.group_name, COUNT(*) AS students,
                       SUM(CASE WHEN p.risk_level = 'Высокий' THEN 1 ELSE 0 END) AS high_risk,
                       SUM(CASE WHEN p.risk_level = 'Средний' THEN 1 ELSE 0 END) AS medium_risk,
                       AVG(p.risk_probability) AS avg_probability,
                       AVG(sf.attendance_rate) AS attendance_rate,
                       AVG(sf.midterm_avg) AS midterm_avg,
                       AVG(sf.submission_on_time_rate) AS on_time_rate
                FROM student_groups g
                JOIN students s ON s.group_id = g.group_id
                JOIN predictions p ON p.student_id = s.student_id AND p.model_run_id = ?
                JOIN student_features sf ON sf.student_id = s.student_id
                WHERE g.group_name = ?
                GROUP BY g.group_name
                """,
                (run_id, group_name.upper()),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def group_table(self) -> pd.DataFrame:
        connection = connect(self.db_path, read_only=True)
        try:
            run_id = self._latest_run(connection)
            return pd.read_sql_query(
                """
                SELECT g.group_name AS 'Группа', COUNT(*) AS 'Студентов',
                       SUM(CASE WHEN p.risk_level='Высокий' THEN 1 ELSE 0 END) AS 'Высокий риск',
                       AVG(p.risk_probability) AS 'Средний риск',
                       AVG(sf.attendance_rate) AS 'Посещаемость',
                       AVG(sf.midterm_avg) AS 'Промежуточный балл'
                FROM students s
                JOIN student_groups g ON g.group_id=s.group_id
                JOIN predictions p ON p.student_id=s.student_id AND p.model_run_id=?
                JOIN student_features sf ON sf.student_id=s.student_id
                GROUP BY g.group_name ORDER BY g.group_name
                """,
                connection,
                params=(run_id,),
            )
        finally:
            connection.close()

    def high_risk_students(self, limit: int = 10, group_name: str | None = None) -> pd.DataFrame:
        limit = max(1, min(int(limit), 50))
        connection = connect(self.db_path, read_only=True)
        try:
            run_id = self._latest_run(connection)
            sql = """
                SELECT s.student_id, s.full_name, g.group_name, p.risk_probability,
                       p.risk_level, sf.attendance_rate, sf.midterm_avg,
                       sf.submission_on_time_rate
                FROM predictions p
                JOIN students s ON s.student_id=p.student_id
                JOIN student_groups g ON g.group_id=s.group_id
                JOIN student_features sf ON sf.student_id=s.student_id
                WHERE p.model_run_id=? AND p.risk_level='Высокий'
            """
            params: list[Any] = [run_id]
            if group_name:
                sql += " AND g.group_name=?"
                params.append(group_name.upper())
            sql += " ORDER BY p.risk_probability DESC LIMIT ?"
            params.append(limit)
            return pd.read_sql_query(sql, connection, params=params)
        finally:
            connection.close()

    def all_predictions(self) -> pd.DataFrame:
        connection = connect(self.db_path, read_only=True)
        try:
            run_id = self._latest_run(connection)
            return pd.read_sql_query(
                """
                SELECT s.student_id, s.full_name, g.group_name, p.risk_probability,
                       p.risk_level, sf.attendance_rate, sf.midterm_avg,
                       sf.submission_on_time_rate, sf.active_days
                FROM predictions p
                JOIN students s ON s.student_id=p.student_id
                JOIN student_groups g ON g.group_id=s.group_id
                JOIN student_features sf ON sf.student_id=s.student_id
                WHERE p.model_run_id=?
                ORDER BY p.risk_probability DESC
                """,
                connection,
                params=(run_id,),
            )
        finally:
            connection.close()

    def course_analysis(self) -> pd.DataFrame:
        connection = connect(self.db_path, read_only=True)
        try:
            return pd.read_sql_query(
                """
                SELECT c.course_code, c.course_name, COUNT(*) AS students,
                       AVG(e.midterm_score) AS midterm_avg,
                       AVG(e.final_grade) AS final_grade_avg,
                       AVG(CASE WHEN e.final_grade=2 THEN 1.0 ELSE 0.0 END) AS failure_rate,
                       (SELECT AVG(a.present * 1.0) FROM attendance a WHERE a.course_code=c.course_code) AS attendance_rate
                FROM courses c
                JOIN enrollments e ON e.course_code=c.course_code
                GROUP BY c.course_code, c.course_name
                ORDER BY failure_rate DESC
                """,
                connection,
            )
        finally:
            connection.close()

    def model_quality(self) -> dict[str, Any]:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))

    def knowledge_search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Семантически-приближённый поиск по локальной базе регламентов."""
        return search_knowledge(query, top_k=top_k)

    def quality_log(self) -> pd.DataFrame:
        connection = connect(self.db_path, read_only=True)
        try:
            return pd.read_sql_query(
                """SELECT source_name, check_name, affected_rows, action_taken
                   FROM data_quality_log ORDER BY source_name, check_id""",
                connection,
            )
        finally:
            connection.close()

    def query_activity(self) -> pd.DataFrame:
        connection = connect(self.db_path, read_only=True)
        try:
            return pd.read_sql_query(
                """
                SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS requests,
                       AVG(response_time_ms) AS avg_response_ms,
                       SUM(llm_used) AS llm_requests,
                       SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS successful
                FROM query_logs GROUP BY substr(created_at, 1, 10) ORDER BY day
                """,
                connection,
            )
        finally:
            connection.close()

    def log_query(
        self,
        session_id: str,
        user_role: str,
        intent: str,
        query_text: str,
        response_time_ms: float,
        result_count: int,
        status: str,
        llm_used: bool,
    ) -> None:
        # Ограничиваем длину, чтобы журнал не превращался в хранилище диалогов.
        safe_text = query_text.replace("\x00", "")[:500]
        connection = connect(self.db_path)
        try:
            connection.execute(
                """INSERT INTO query_logs
                   (created_at, session_id, user_role, intent, query_text,
                    response_time_ms, result_count, status, llm_used)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(), session_id[:80], user_role,
                    intent, safe_text, round(response_time_ms, 2), int(result_count),
                    status, int(llm_used),
                ),
            )
            connection.commit()
        finally:
            connection.close()


def recommendations_from_factors(factors: list[dict[str, Any]]) -> list[str]:
    """Преобразовать объясняющие факторы в поддерживающие действия."""
    rules = {
        "attendance_rate": "Согласовать план восстановления посещаемости и разобрать причины пропусков.",
        "late_rate": "Скорректировать расписание и поставить напоминания о начале занятий.",
        "submission_on_time_rate": "Разбить ближайшие задания на короткие этапы с промежуточными сроками.",
        "midterm_avg": "Назначить консультацию по темам с низким промежуточным результатом.",
        "assignment_avg": "Провести разбор ошибок в практических заданиях и повторную тренировку.",
        "low_midterm_share": "Составить приоритетный план закрытия пробелов по двум наиболее сложным дисциплинам.",
        "attempts_avg": "Проверить, какие типовые ошибки приводят к повторным попыткам.",
        "previous_gpa": "Предложить регулярное сопровождение тьютора и короткие еженедельные контрольные точки.",
        "active_days": "Запланировать регулярные короткие сессии работы в LMS вместо редких длинных сессий.",
        "lms_events_per_course": "Порекомендовать систематическую работу с материалами LMS по календарному плану.",
        "quiz_attempts_per_course": "Добавить тренировочные тесты с обратной связью.",
        "forum_posts_per_course": "Предложить задать вопросы преподавателю или участвовать в учебном обсуждении.",
        "avg_session_minutes": "Скорректировать режим самостоятельной работы и применять короткие фокус-сессии.",
        "admission_score": "Проверить базовые знания и предложить выравнивающие материалы.",
    }
    result: list[str] = []
    for factor in factors:
        recommendation = rules.get(factor.get("feature"))
        if recommendation and recommendation not in result:
            result.append(recommendation)
    if not result:
        result.append("Сохранить наблюдение и повторно оценить риск после следующей контрольной точки.")
    return result[:3]
