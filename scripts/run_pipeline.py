#!/usr/bin/env python3
"""Один воспроизводимый запуск всех этапов проекта."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.eda import generate_eda
from src.etl import run_etl
from src.features import build_features
from src.generate_data import generate_raw_data
from src.knowledge import build_knowledge_index
from src.train import train_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Полный конвейер: generate → ETL → features → train → EDA")
    parser.add_argument("--students", type=int, default=420)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()

    started = time.perf_counter()
    if not args.skip_generate:
        print("[1/6] Генерация синтетических источников…", flush=True)
        counts = generate_raw_data(args.students, args.seed)
        print("      " + ", ".join(f"{name}: {value}" for name, value in counts.items()))
    else:
        print("[1/6] Генерация пропущена.")

    print("[2/6] ETL и нормализованная SQLite…", flush=True)
    etl = run_etl()
    print(f"      Загружено студентов: {etl['loaded_rows']['students']}; проблем качества: {etl['quality_issues_detected']}")

    print("[3/6] Feature engineering…", flush=True)
    data = build_features()
    print(f"      Наблюдений: {len(data)}; доля риска: {data['at_risk'].mean():.1%}")

    print("[4/6] Векторный TF-IDF индекс базы знаний…", flush=True)
    knowledge = build_knowledge_index()
    print(f"      Документов: {knowledge['documents']}; фрагментов: {knowledge['chunks']}; словарь: {knowledge['vocabulary']}")

    print("[5/6] Обучение и независимая оценка…", flush=True)
    metrics = train_model()
    print(f"      {metrics['selected_model']}; test F1={metrics['test']['f1']:.3f}; ROC-AUC={metrics['test']['roc_auc']:.3f}")

    print("[6/6] EDA и иллюстрации…", flush=True)
    eda = generate_eda()
    print(f"      Сформировано {len(eda['figures'])} графиков")
    print(f"Готово за {time.perf_counter() - started:.1f} с. Запуск интерфейса: streamlit run app.py")


if __name__ == "__main__":
    main()
