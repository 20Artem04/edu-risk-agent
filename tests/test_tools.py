from __future__ import annotations

from src.tools import AnalyticsTools


def test_high_risk_tool_is_sorted_and_limited() -> None:
    frame = AnalyticsTools().high_risk_students(limit=5)
    assert 0 < len(frame) <= 5
    assert frame["risk_probability"].is_monotonic_decreasing
    assert (frame["risk_level"] == "Высокий").all()


def test_group_aggregates_cover_all_students() -> None:
    tools = AnalyticsTools()
    table = tools.group_table()
    overview = tools.overview()
    assert int(table["Студентов"].sum()) == overview["students"]
