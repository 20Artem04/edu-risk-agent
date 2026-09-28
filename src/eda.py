"""Разведочный анализ и формирование статических иллюстраций отчёта."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from src.config import DB_PATH, FEATURE_COLUMNS, FEATURE_LABELS_RU, FIGURE_DIR, METRICS_PATH, PROCESSED_DIR, ensure_directories
from src.db import connect

COLORS = {"blue": "#2563EB", "cyan": "#06B6D4", "amber": "#F59E0B", "red": "#EF4444", "green": "#10B981", "ink": "#0F172A", "muted": "#64748B"}


def _finish(fig: plt.Figure, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def generate_eda(
    dataset_path: Path = PROCESSED_DIR / "model_dataset.csv",
    metrics_path: Path = METRICS_PATH,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    ensure_directories()
    sns.set_theme(style="whitegrid", font="DejaVu Sans")
    plt.rcParams.update({"axes.titleweight": "bold", "axes.titlesize": 13, "figure.dpi": 120})
    data = pd.read_csv(dataset_path, encoding="utf-8-sig")

    # 1. Баланс классов.
    counts = data["at_risk"].value_counts().reindex([0, 1], fill_value=0)
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    bars = ax.bar(["Нет риска", "Есть риск"], counts.values, color=[COLORS["blue"], COLORS["red"]], width=0.58)
    ax.set_title("Распределение целевого класса")
    ax.set_ylabel("Количество студентов")
    ax.bar_label(bars, labels=[f"{value}\n({value / len(data):.1%})" for value in counts.values], padding=4)
    ax.set_ylim(0, max(counts.values) * 1.18)
    _finish(fig, FIGURE_DIR / "target_distribution.png")

    # 2. Ключевые распределения.
    key_features = ["attendance_rate", "previous_gpa", "midterm_avg", "submission_on_time_rate"]
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.4))
    for ax, feature in zip(axes.flat, key_features):
        sns.histplot(data=data, x=feature, hue="at_risk", bins=20, stat="density", common_norm=False, element="step", palette={0: COLORS["blue"], 1: COLORS["red"]}, ax=ax)
        ax.set_title(FEATURE_LABELS_RU[feature])
        ax.set_xlabel("")
        legend = ax.get_legend()
        if legend is not None:
            legend.set_title("Риск")
            for text, label in zip(legend.texts, ["Нет", "Есть"]):
                text.set_text(label)
    fig.suptitle("Распределения ключевых признаков по классам", fontsize=15, fontweight="bold", y=1.01)
    _finish(fig, FIGURE_DIR / "feature_distributions.png")

    # 3. Корреляции.
    correlations = data[FEATURE_COLUMNS + ["at_risk"]].corr(method="spearman")
    short_labels = [FEATURE_LABELS_RU.get(value, "Риск") for value in correlations.columns]
    fig, ax = plt.subplots(figsize=(13.5, 10.5))
    sns.heatmap(correlations, cmap="vlag", center=0, vmin=-1, vmax=1, xticklabels=short_labels, yticklabels=short_labels, ax=ax, cbar_kws={"label": "ρ Спирмена"})
    ax.set_title("Корреляционная матрица признаков")
    ax.tick_params(axis="x", rotation=52, labelsize=8)
    ax.tick_params(axis="y", rotation=0, labelsize=8)
    _finish(fig, FIGURE_DIR / "correlation_heatmap.png")

    # 4. Риск по группам с доверительными ориентировочными интервалами.
    grouped = data.groupby("group_name")["at_risk"].agg(["mean", "count", "sum"]).reset_index().sort_values("mean")
    grouped["se"] = np.sqrt(grouped["mean"] * (1 - grouped["mean"]) / grouped["count"])
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(grouped["group_name"], grouped["mean"], color=COLORS["cyan"])
    ax.errorbar(grouped["mean"], grouped["group_name"], xerr=1.96 * grouped["se"], fmt="none", ecolor=COLORS["ink"], capsize=3)
    ax.axvline(data["at_risk"].mean(), color=COLORS["red"], linestyle="--", label=f"Среднее: {data['at_risk'].mean():.1%}")
    ax.set_xlim(0, min(1, grouped["mean"].max() + 0.22))
    ax.set_xlabel("Доля студентов группы риска")
    ax.set_ylabel("")
    ax.set_title("Наблюдаемая доля риска по учебным группам")
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.legend(loc="lower right")
    _finish(fig, FIGURE_DIR / "risk_by_group.png")

    # 5. Связь посещаемости и прогноза/класса.
    fig, ax = plt.subplots(figsize=(8.8, 5.4))
    sns.scatterplot(data=data, x="attendance_rate", y="midterm_avg", hue="at_risk", palette={0: COLORS["blue"], 1: COLORS["red"]}, alpha=0.67, s=40, ax=ax)
    ax.set_xlabel("Посещаемость")
    ax.set_ylabel("Средний промежуточный балл")
    ax.set_title("Риск в пространстве ранних индикаторов")
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles=handles, labels=["Нет риска", "Есть риск"], title="Фактический класс")
    _finish(fig, FIGURE_DIR / "risk_scatter.png")

    metrics: dict[str, Any] = {}
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        cm = np.array(metrics["test"]["confusion_matrix"])
        fig, ax = plt.subplots(figsize=(5.8, 5.0))
        sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", cbar=False, xticklabels=["Нет риска", "Риск"], yticklabels=["Нет риска", "Риск"], ax=ax)
        ax.set_xlabel("Прогноз")
        ax.set_ylabel("Факт")
        ax.set_title("Матрица ошибок на тестовой выборке")
        _finish(fig, FIGURE_DIR / "confusion_matrix.png")

        roc = metrics["roc_curve"]
        fig, ax = plt.subplots(figsize=(6.5, 5.3))
        ax.plot(roc["fpr"], roc["tpr"], color=COLORS["blue"], linewidth=2.4, label=f"Модель, AUC={metrics['test']['roc_auc']:.3f}")
        ax.plot([0, 1], [0, 1], linestyle="--", color=COLORS["muted"], label="Случайный классификатор")
        ax.set(xlabel="False Positive Rate", ylabel="True Positive Rate", title="ROC-кривая на тестовой выборке")
        ax.legend(loc="lower right")
        ax.set_aspect("equal", adjustable="box")
        _finish(fig, FIGURE_DIR / "roc_curve.png")

        importance = pd.DataFrame(metrics["feature_importance"]).sort_values("importance").tail(10)
        fig, ax = plt.subplots(figsize=(9.2, 6))
        ax.barh(importance["label_ru"], importance["importance"], color=COLORS["blue"])
        ax.set_xlabel("Нормированная permutation importance")
        ax.set_title("Наиболее значимые признаки модели")
        _finish(fig, FIGURE_DIR / "feature_importance.png")

    # 6. Журнал очистки.
    connection = connect(db_path, read_only=True)
    try:
        quality = pd.read_sql_query("SELECT source_name, SUM(affected_rows) AS affected_rows FROM data_quality_log GROUP BY source_name ORDER BY affected_rows DESC", connection)
    finally:
        connection.close()
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    sns.barplot(data=quality, x="affected_rows", y="source_name", color=COLORS["amber"], ax=ax)
    ax.set_xlabel("Число обнаруженных проблемных строк/значений")
    ax.set_ylabel("")
    ax.set_title("Результаты автоматических проверок качества")
    _finish(fig, FIGURE_DIR / "data_quality.png")

    target_corr = correlations["at_risk"].drop("at_risk").sort_values(key=np.abs, ascending=False)
    summary = {
        "rows": len(data),
        "risk_rate": round(float(data["at_risk"].mean()), 4),
        "numeric_descriptive_statistics": data[FEATURE_COLUMNS].describe().round(4).to_dict(),
        "group_risk": grouped[["group_name", "count", "sum", "mean"]].round(4).to_dict(orient="records"),
        "top_target_correlations": [
            {"feature": feature, "label_ru": FEATURE_LABELS_RU[feature], "spearman_rho": round(float(value), 4)}
            for feature, value in target_corr.head(8).items()
        ],
        "figures": sorted(
            path.name for path in FIGURE_DIR.glob("*.png")
            if path.name not in {"architecture.png", "er_diagram.png"}
        ),
    }
    (PROCESSED_DIR / "eda_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="EDA и графики")
    parser.add_argument("--dataset", type=Path, default=PROCESSED_DIR / "model_dataset.csv")
    parser.add_argument("--metrics", type=Path, default=METRICS_PATH)
    args = parser.parse_args()
    summary = generate_eda(args.dataset, args.metrics)
    print(f"Сформировано графиков: {len(summary['figures'])}")


if __name__ == "__main__":
    main()
