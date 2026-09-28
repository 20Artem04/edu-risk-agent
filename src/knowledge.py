"""Небольшой локальный RAG-индекс внутренних методических текстов на TF-IDF."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from src.config import KNOWLEDGE_INDEX_PATH, PROCESSED_DIR, PROJECT_ROOT, ensure_directories

KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
RUSSIAN_STOPWORDS = [
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все", "она", "так", "его",
    "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по", "только", "ее", "мне", "было", "вот", "от", "меня",
    "еще", "нет", "о", "из", "ему", "теперь", "когда", "даже", "ну", "ли", "если", "уже", "или", "ни", "быть",
    "был", "него", "до", "вас", "нибудь", "опять", "уж", "вам", "ведь", "там", "потом", "себя", "ничего", "ей",
    "может", "они", "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя", "их", "чем", "была", "сам", "чтоб",
    "без", "будто", "чего", "раз", "тоже", "себе", "под", "будет", "ж", "тогда", "кто", "этот", "того", "потому",
    "этого", "какой", "совсем", "ним", "здесь", "этом", "один", "почти", "мой", "тем", "чтобы", "нее", "сейчас",
]


def _chunks_from_markdown(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    document_title = path.stem
    heading = document_title
    chunks: list[dict[str, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        body = " ".join(piece.strip() for piece in buffer if piece.strip()).strip()
        if body:
            chunks.append({"source": path.name, "section": heading, "text": body})
        buffer = []

    for line in text.splitlines():
        if line.startswith("# "):
            flush()
            document_title = line[2:].strip()
            heading = document_title
        elif line.startswith("## "):
            flush()
            heading = line[3:].strip()
        elif line.strip():
            buffer.append(re.sub(r"^[*-]\s+", "", line.strip()))
    flush()
    for chunk in chunks:
        chunk["document"] = document_title
    return chunks


def build_knowledge_index(knowledge_dir: Path = KNOWLEDGE_DIR, output_path: Path = KNOWLEDGE_INDEX_PATH) -> dict[str, int]:
    """Разбить Markdown на секции и построить разреженную TF-IDF-матрицу."""
    ensure_directories()
    paths = sorted(knowledge_dir.glob("*.md"))
    if not paths:
        raise FileNotFoundError(f"В {knowledge_dir} нет Markdown-документов")
    chunks: list[dict[str, str]] = []
    for path in paths:
        chunks.extend(_chunks_from_markdown(path))
    frame = pd.DataFrame(chunks)
    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words=RUSSIAN_STOPWORDS,
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True,
        token_pattern=r"(?u)\b[\w-]{2,}\b",
    )
    matrix = vectorizer.fit_transform(frame["text"])
    artifact = {"vectorizer": vectorizer, "matrix": matrix, "chunks": frame.to_dict(orient="records"), "method": "TF-IDF word 1-2 grams"}
    joblib.dump(artifact, output_path)
    frame.to_csv(PROCESSED_DIR / "knowledge_chunks.csv", index=False, encoding="utf-8-sig")
    return {"documents": len(paths), "chunks": len(frame), "vocabulary": len(vectorizer.vocabulary_)}


def search_knowledge(query: str, top_k: int = 3, index_path: Path = KNOWLEDGE_INDEX_PATH, min_score: float = 0.03) -> list[dict[str, Any]]:
    """Вернуть наиболее близкие секции. TF-IDF-векторы L2-нормированы, поэтому dot=cosine."""
    if not index_path.exists():
        build_knowledge_index()
    artifact = joblib.load(index_path)
    query_vector = artifact["vectorizer"].transform([query])
    scores = linear_kernel(query_vector, artifact["matrix"]).ravel()
    indices = scores.argsort()[::-1][: max(1, min(int(top_k), 8))]
    results = []
    for index in indices:
        score = float(scores[index])
        if score < min_score:
            continue
        chunk = dict(artifact["chunks"][int(index)])
        chunk["score"] = round(score, 4)
        results.append(chunk)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Построение TF-IDF индекса базы знаний")
    parser.add_argument("--knowledge-dir", type=Path, default=KNOWLEDGE_DIR)
    args = parser.parse_args()
    result = build_knowledge_index(args.knowledge_dir)
    print(f"Индекс: {result['documents']} документов, {result['chunks']} фрагментов, словарь {result['vocabulary']}")


if __name__ == "__main__":
    main()
