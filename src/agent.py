"""Диалоговый агент с инструментами, RBAC и опциональной локальной LLM."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.config import PROJECT_ROOT
from src.tools import AnalyticsTools, recommendations_from_factors

ROLE_STUDENT = "Студент"
ROLE_TEACHER = "Преподаватель"
ROLE_DEAN = "Деканат"


@dataclass
class AgentResponse:
    answer: str
    intent: str
    data: Any = None
    sources: list[str] = field(default_factory=list)
    result_count: int = 0
    llm_used: bool = False
    status: str = "ok"


class OllamaClient:
    """Минимальный клиент локального Ollama; платные внешние API не нужны."""

    def __init__(self) -> None:
        self.enabled = os.getenv("LLM_PROVIDER", "none").lower() == "ollama"
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self.model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
        self.system_prompt = (PROJECT_ROOT / "prompts" / "system_prompt.txt").read_text(encoding="utf-8")

    def status(self) -> tuple[bool, str]:
        if not self.enabled:
            return False, "LLM отключена; используется воспроизводимый шаблонный режим"
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=0.8)
            response.raise_for_status()
            names = [item.get("name", "") for item in response.json().get("models", [])]
            available = any(name == self.model or name.startswith(f"{self.model}:") for name in names)
            return available, (f"Ollama: {self.model}" if available else f"Модель {self.model} не загружена в Ollama")
        except requests.RequestException:
            return False, "Ollama недоступна; используется шаблонный режим"

    def generate(self, question: str, role: str, context: Any, draft: str) -> str | None:
        if not self.enabled:
            return None
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0.15, "num_predict": 450},
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"РОЛЬ ПОЛЬЗОВАТЕЛЯ: {role}\n"
                        f"ВОПРОС: {question}\n\n"
                        f"КОНТЕКСТ ИНСТРУМЕНТА:\n{json.dumps(context, ensure_ascii=False, default=str)}\n\n"
                        f"ПРОВЕРЕННЫЙ ЧЕРНОВИК:\n{draft}\n\n"
                        "Сформулируй финальный ответ. Не меняй числа и не добавляй факты."
                    ),
                },
            ],
        }
        try:
            response = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=45)
            response.raise_for_status()
            text = response.json().get("message", {}).get("content", "").strip()
            return text or None
        except (requests.RequestException, ValueError):
            return None


class RiskAgent:
    """Оркестратор: определяет намерение, вызывает инструмент и формирует ответ."""

    def __init__(self, tools: AnalyticsTools | None = None, session_id: str | None = None) -> None:
        self.tools = tools or AnalyticsTools()
        self.llm = OllamaClient()
        self.session_id = session_id or str(uuid.uuid4())

    @staticmethod
    def _group_from_text(text: str) -> str | None:
        match = re.search(r"(?:ПИ|пи)\s*[-–—]?\s*(40[1-9])", text)
        return f"ПИ-{match.group(1)}" if match else None

    @staticmethod
    def _student_from_text(text: str) -> str | None:
        match = re.search(r"STU\s*[-]?\s*(\d{4})", text, flags=re.IGNORECASE)
        return f"STU{match.group(1)}" if match else None

    @staticmethod
    def _limit_from_text(text: str, default: int = 10) -> int:
        match = re.search(r"(?:топ|покажи|выведи|список)\s*(\d{1,2})", text, flags=re.IGNORECASE)
        return max(1, min(int(match.group(1)), 50)) if match else default

    def _intent(self, question: str, own_student_id: str | None) -> tuple[str, dict[str, Any]]:
        text = question.lower().strip()
        student_id = self._student_from_text(question)
        group_name = self._group_from_text(question)
        if student_id or any(token in text for token in ["мой риск", "моя карточ", "мои показател", "что мне делать"]):
            return "student_card", {"student_id": student_id or own_student_id}
        if any(token in text for token in ["f1", "roc", "auc", "точност", "качество модел", "метрик", "алгоритм"]):
            return "model_quality", {}
        if any(token in text for token in ["дисциплин", "предмет", "курс слож", "по курсам", "по предметам"]):
            return "course_analysis", {}
        if group_name or ("групп" in text and any(token in text for token in ["риск", "свод", "показател"])):
            return "group_summary", {"group_name": group_name}
        if any(token in text for token in ["кто в риск", "список риск", "высокий риск", "топ", "приоритетн"]):
            return "high_risk", {"group_name": group_name, "limit": self._limit_from_text(question)}
        if any(token in text for token in ["сводк", "в целом", "общая", "сколько студент", "обзор", "состояние"]):
            return "overview", {}
        if any(token in text for token in ["регламент", "поддержк", "конфиденц", "приват", "хранить дан", "как улучшить", "что означает вероят", "интерпрет", "посещаемость улучш", "сроки задан", "качество дан"]):
            return "knowledge_search", {"query": question}
        return "help", {}

    @staticmethod
    def _student_draft(card: dict[str, Any]) -> str:
        factors = card["top_factors"]
        factor_lines = "\n".join(
            f"- **{item['label']}**: {item['value']:.2f} — {item['effect']}." for item in factors
        ) or "- Выраженные факторы не выделены."
        actions = recommendations_from_factors(factors)
        action_lines = "\n".join(f"{index}. {action}" for index, action in enumerate(actions, 1))
        return (
            f"### {card['full_name']} · {card['student_id']}\n\n"
            f"**Уровень риска:** {card['risk_level']}  \n"
            f"**Оценка вероятности:** {card['risk_probability']:.1%}\n\n"
            "Это вероятностный сигнал ранней поддержки, а не предрешённая оценка.\n\n"
            f"**Основные факторы**\n{factor_lines}\n\n"
            f"**Рекомендуемые действия**\n{action_lines}"
        )

    @staticmethod
    def _df_markdown(frame: pd.DataFrame, columns: dict[str, str], percent: set[str] | None = None) -> str:
        percent = percent or set()
        view = frame[list(columns)].rename(columns=columns).copy()
        for original, renamed in columns.items():
            if original in percent:
                view[renamed] = view[renamed].map(lambda value: f"{value:.1%}")
            elif pd.api.types.is_float_dtype(view[renamed]):
                view[renamed] = view[renamed].map(lambda value: f"{value:.2f}")
        return view.to_markdown(index=False)

    def _execute(self, intent: str, params: dict[str, Any], role: str, own_student_id: str | None) -> AgentResponse:
        if intent == "student_card":
            student_id = params.get("student_id")
            if not student_id:
                return AgentResponse("Укажите идентификатор студента в формате `STU0001`.", intent, status="needs_input")
            if role == ROLE_STUDENT and student_id.upper() != (own_student_id or "").upper():
                return AgentResponse("Доступ запрещён: студент может просматривать только собственную карточку.", intent, status="forbidden")
            card = self.tools.student_card(student_id)
            if card is None:
                return AgentResponse(f"Студент `{student_id}` не найден.", intent, status="not_found")
            return AgentResponse(self._student_draft(card), intent, card, ["students", "student_features", "predictions"], 1)

        if intent in {"high_risk", "group_summary"} and role == ROLE_STUDENT:
            return AgentResponse("Агрегированные списки и карточки других студентов доступны только преподавателю или деканату.", intent, status="forbidden")

        if intent == "overview":
            data = self.tools.overview()
            answer = (
                "### Общая сводка\n\n"
                f"- Студентов: **{data['students']}**, учебных групп: **{data['groups']}**.\n"
                f"- Высокий риск: **{data['high_risk']}** ({data['high_risk'] / max(data['students'], 1):.1%}).\n"
                f"- Средний риск: **{data['medium_risk']}** ({data['medium_risk'] / max(data['students'], 1):.1%}).\n"
                f"- Средняя посещаемость: **{data['attendance_rate']:.1%}**.\n"
                f"- Средний промежуточный балл: **{data['midterm_avg']:.1f}/100**.\n\n"
                "Сводка предназначена для определения приоритетов поддержки; прогноз не является основанием для санкций."
            )
            return AgentResponse(answer, intent, data, ["predictions", "student_features"], data["students"])

        if intent == "group_summary":
            group_name = params.get("group_name")
            if not group_name:
                return AgentResponse("Уточните группу, например: `ПИ-401`.", intent, status="needs_input")
            data = self.tools.group_summary(group_name)
            if data is None:
                return AgentResponse(f"Группа `{group_name}` не найдена.", intent, status="not_found")
            answer = (
                f"### Группа {data['group_name']}\n\n"
                f"- Студентов: **{data['students']}**.\n"
                f"- Высокий риск: **{data['high_risk']}**, средний риск: **{data['medium_risk']}**.\n"
                f"- Средняя вероятность риска: **{data['avg_probability']:.1%}**.\n"
                f"- Посещаемость: **{data['attendance_rate']:.1%}**.\n"
                f"- Работы вовремя: **{data['on_time_rate']:.1%}**.\n"
                f"- Промежуточный балл: **{data['midterm_avg']:.1f}/100**."
            )
            return AgentResponse(answer, intent, data, ["student_groups", "predictions", "student_features"], int(data["students"]))

        if intent == "high_risk":
            frame = self.tools.high_risk_students(params.get("limit", 10), params.get("group_name"))
            if frame.empty:
                return AgentResponse("Студенты с высоким уровнем риска по заданному фильтру не найдены.", intent, frame, result_count=0)
            table = self._df_markdown(
                frame,
                {
                    "student_id": "ID",
                    "full_name": "Студент",
                    "group_name": "Группа",
                    "risk_probability": "Риск",
                    "attendance_rate": "Посещаемость",
                    "midterm_avg": "Промеж. балл",
                },
                {"risk_probability", "attendance_rate"},
            )
            answer = f"### Приоритетный список для проверки и поддержки\n\n{table}\n\nПеред контактом рекомендуется проверить актуальность исходных данных. Список нельзя использовать для автоматических санкций."
            return AgentResponse(answer, intent, frame.to_dict(orient="records"), ["predictions", "students", "student_features"], len(frame))

        if intent == "course_analysis":
            frame = self.tools.course_analysis()
            table = self._df_markdown(
                frame,
                {
                    "course_code": "Код",
                    "course_name": "Дисциплина",
                    "midterm_avg": "Промеж. балл",
                    "failure_rate": "Доля двоек",
                    "attendance_rate": "Посещаемость",
                },
                {"failure_rate", "attendance_rate"},
            )
            answer = f"### Аналитика по дисциплинам\n\n{table}\n\nВысокая доля риска требует содержательного анализа сложности, оценивания и доступности поддержки, а не только сравнения студентов."
            return AgentResponse(answer, intent, frame.to_dict(orient="records"), ["courses", "enrollments", "attendance"], len(frame))

        if intent == "model_quality":
            data = self.tools.model_quality()
            test = data["test"]
            answer = (
                "### Качество модели\n\n"
                f"- Алгоритм: **{data['selected_model']}**.\n"
                f"- Тестовая выборка: **{data['dataset']['test_rows']}** наблюдений.\n"
                f"- F1: **{test['f1']:.3f}**, recall: **{test['recall']:.3f}**, precision: **{test['precision']:.3f}**.\n"
                f"- ROC-AUC: **{test['roc_auc']:.3f}**, Brier score: **{test['brier']:.3f}**.\n"
                f"- Порог: **{data['threshold']:.2f}**.\n\n"
                "Метрики получены на синтетических данных и не доказывают качество на реальных студентах."
            )
            return AgentResponse(answer, intent, data, ["models/metrics.json", "model_runs"], data["dataset"]["test_rows"])

        if intent == "knowledge_search":
            chunks = self.tools.knowledge_search(params.get("query", ""), top_k=3)
            if not chunks:
                return AgentResponse(
                    "В локальной базе знаний нет достаточно близкого фрагмента. Уточните вопрос или обратитесь к утверждённому регламенту вуза.",
                    intent,
                    status="not_found",
                )
            sections = []
            for item in chunks:
                sections.append(f"**{item['document']} · {item['section']}**  \n{item['text']}")
            answer = "### Поиск по базе знаний\n\n" + "\n\n".join(sections) + "\n\n*Фрагменты найдены локальным TF-IDF-поиском; перед реальным применением сверяйтесь с действующими документами вуза.*"
            return AgentResponse(answer, intent, chunks, [f"knowledge/{item['source']}" for item in chunks], len(chunks))

        help_text = """### Что можно спросить

- «Покажи общую сводку»;
- «Какой риск у STU0001?»;
- «Сводка по группе ПИ-401»;
- «Покажи топ 10 студентов с высоким риском»;
- «Какие дисциплины самые сложные?»;
- «Какое качество модели?»;
- «Как организована ранняя поддержка?»

Ответы строятся по проверенным SQL-инструментам. Для свободной формулировки текста можно включить локальную Ollama; без неё все функции работают в шаблонном режиме."""
        return AgentResponse(help_text, intent, sources=["Справка агента"])

    def ask(self, question: str, role: str = ROLE_DEAN, own_student_id: str | None = None) -> AgentResponse:
        started = time.perf_counter()
        intent, params = self._intent(question, own_student_id)
        try:
            response = self._execute(intent, params, role, own_student_id)
            llm_text = None
            # Ошибки доступа и запрос на уточнение не передаём LLM.
            if response.status == "ok" and intent != "help":
                llm_text = self.llm.generate(question, role, response.data, response.answer)
            if llm_text:
                response.answer = llm_text
                response.llm_used = True
        except Exception as exc:  # журналируем, но не раскрываем трассировку в UI
            response = AgentResponse(f"Не удалось выполнить запрос: {exc}", intent, status="error")
        elapsed = (time.perf_counter() - started) * 1000
        try:
            self.tools.log_query(
                self.session_id, role, response.intent, question, elapsed,
                response.result_count, response.status, response.llm_used,
            )
        except Exception:
            pass
        return response
