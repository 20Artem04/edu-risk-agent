from __future__ import annotations

from src.agent import ROLE_DEAN, ROLE_STUDENT, RiskAgent


def test_student_cannot_read_another_card() -> None:
    agent = RiskAgent(session_id="pytest-rbac")
    response = agent.ask("Какой риск у STU0002?", role=ROLE_STUDENT, own_student_id="STU0001")
    assert response.status == "forbidden"


def test_dean_can_get_overview() -> None:
    agent = RiskAgent(session_id="pytest-overview")
    response = agent.ask("Покажи общую сводку", role=ROLE_DEAN)
    assert response.status == "ok"
    assert response.data["students"] > 0
    assert "Общая сводка" in response.answer


def test_student_own_card_probability_is_valid() -> None:
    agent = RiskAgent(session_id="pytest-card")
    response = agent.ask("Какой мой риск?", role=ROLE_STUDENT, own_student_id="STU0001")
    assert response.status == "ok"
    assert 0.0 <= response.data["risk_probability"] <= 1.0
