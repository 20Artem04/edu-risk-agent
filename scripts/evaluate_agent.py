#!/usr/bin/env python3
"""Оценка маршрутизации намерений и задержки детерминированного агента."""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LLM_PROVIDER"] = "none"

from src.agent import ROLE_DEAN, RiskAgent

CASES = [
    ("Покажи общую сводку", "overview"),
    ("Что происходит в целом?", "overview"),
    ("Сколько студентов в системе?", "overview"),
    ("Какой риск у STU0001?", "student_card"),
    ("Покажи карточку STU0310", "student_card"),
    ("Что мне делать?", "student_card"),
    ("Сводка по группе ПИ-401", "group_summary"),
    ("Показатели группы пи 402", "group_summary"),
    ("Риск группы ПИ–407", "group_summary"),
    ("Покажи список риска", "high_risk"),
    ("Топ 5 студентов с высоким риском", "high_risk"),
    ("Кто в риске?", "high_risk"),
    ("Какие дисциплины самые сложные?", "course_analysis"),
    ("Покажи аналитику по курсам", "course_analysis"),
    ("Что по предметам?", "course_analysis"),
    ("Какое качество модели?", "model_quality"),
    ("Какой ROC-AUC?", "model_quality"),
    ("Покажи F1 и recall", "model_quality"),
    ("Как организована ранняя поддержка?", "knowledge_search"),
    ("Как интерпретировать вероятность риска?", "knowledge_search"),
    ("Какой алгоритм используется?", "model_quality"),
    ("Привет, что ты умеешь?", "help"),
    ("Дай примеры вопросов", "help"),
]


def main() -> None:
    agent = RiskAgent(session_id="agent-evaluation")
    route_results = []
    for question, expected in CASES:
        actual, _ = agent._intent(question, own_student_id="STU0001")
        route_results.append({"question": question, "expected": expected, "actual": actual, "correct": expected == actual})

    timings = []
    status_ok = 0
    benchmark_questions = [
        "Покажи общую сводку",
        "Какой риск у STU0001?",
        "Сводка по группе ПИ-401",
        "Покажи топ 5 студентов с высоким риском",
        "Какие дисциплины самые сложные?",
        "Какое качество модели?",
    ]
    for _ in range(10):
        for question in benchmark_questions:
            started = time.perf_counter()
            response = agent.ask(question, role=ROLE_DEAN, own_student_id=None)
            timings.append((time.perf_counter() - started) * 1000)
            status_ok += response.status == "ok"

    result = {
        "mode": "deterministic_no_llm",
        "intent_cases": len(CASES),
        "intent_correct": sum(row["correct"] for row in route_results),
        "intent_accuracy": round(sum(row["correct"] for row in route_results) / len(route_results), 4),
        "route_results": route_results,
        "latency_requests": len(timings),
        "successful_requests": status_ok,
        "latency_ms": {
            "mean": round(statistics.mean(timings), 3),
            "median": round(statistics.median(timings), 3),
            "p95": round(sorted(timings)[int(0.95 * (len(timings) - 1))], 3),
            "max": round(max(timings), 3),
        },
        "note": "Локальный замер на SQLite без сетевой LLM; задержка UI и холодный старт Streamlit не включены.",
    }
    output = ROOT / "reports" / "agent_evaluation.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "route_results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
