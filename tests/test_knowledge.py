from __future__ import annotations

from src.knowledge import search_knowledge


def test_knowledge_search_returns_relevant_section() -> None:
    results = search_knowledge("Как интерпретировать вероятность риска модели?", top_k=3)
    assert results
    combined = " ".join(item["text"].lower() for item in results)
    assert "вероят" in combined
    assert all(0 <= item["score"] <= 1 for item in results)
