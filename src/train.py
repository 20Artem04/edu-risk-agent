"""Обучение, валидация и оценка модели академического риска."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.config import (
    DB_PATH,
    FEATURE_COLUMNS,
    FEATURE_LABELS_RU,
    METRICS_PATH,
    MODEL_CARD_PATH,
    MODEL_DIR,
    MODEL_PATH,
    PROCESSED_DIR,
    PROJECT_ROOT,
    RANDOM_SEED,
    ensure_directories,
)
from src.db import connect


def _metrics(y_true: pd.Series | np.ndarray, probability: np.ndarray, threshold: float) -> dict[str, float | list[list[int]]]:
    prediction = (probability >= threshold).astype(int)
    return {
        "accuracy": round(float(accuracy_score(y_true, prediction)), 4),
        "precision": round(float(precision_score(y_true, prediction, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, prediction, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, prediction, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, probability)), 4),
        "average_precision": round(float(average_precision_score(y_true, probability)), 4),
        "brier": round(float(brier_score_loss(y_true, probability)), 4),
        "confusion_matrix": confusion_matrix(y_true, prediction, labels=[0, 1]).astype(int).tolist(),
    }


def _best_threshold(y_true: pd.Series, probability: np.ndarray) -> tuple[float, float]:
    candidates = np.arange(0.20, 0.801, 0.01)
    scores = [f1_score(y_true, probability >= value, zero_division=0) for value in candidates]
    best_index = int(np.argmax(scores))
    return round(float(candidates[best_index]), 2), round(float(scores[best_index]), 4)


def _factor_payload(
    row: pd.Series,
    importance: dict[str, float],
    directions: dict[str, int],
    medians: dict[str, float],
    iqrs: dict[str, float],
    n: int = 3,
) -> list[dict[str, Any]]:
    impacts = []
    for feature in FEATURE_COLUMNS:
        scale = max(float(iqrs[feature]), 1e-6)
        standardised = (float(row[feature]) - float(medians[feature])) / scale
        impact = standardised * float(directions[feature]) * float(importance[feature])
        impacts.append(
            {
                "feature": feature,
                "label": FEATURE_LABELS_RU[feature],
                "value": round(float(row[feature]), 3),
                "impact": round(float(impact), 5),
                "effect": "повышает риск" if impact > 0 else "снижает риск",
            }
        )
    positive = sorted((item for item in impacts if item["impact"] > 0), key=lambda item: item["impact"], reverse=True)
    selected = positive[:n] if positive else sorted(impacts, key=lambda item: abs(item["impact"]), reverse=True)[:n]
    return selected


def train_model(dataset_path: Path = PROCESSED_DIR / "model_dataset.csv", db_path: Path = DB_PATH) -> dict[str, Any]:
    """Обучить модели, выбрать по валидации и один раз оценить на тесте."""
    ensure_directories()
    data = pd.read_csv(dataset_path, encoding="utf-8-sig")
    missing = set(FEATURE_COLUMNS + ["at_risk", "student_id"]) - set(data.columns)
    if missing:
        raise ValueError(f"В датасете нет полей: {sorted(missing)}")

    X = data[FEATURE_COLUMNS].copy()
    y = data["at_risk"].astype(int)
    indices = np.arange(len(data))
    dev_idx, test_idx = train_test_split(indices, test_size=0.20, stratify=y, random_state=RANDOM_SEED)
    train_idx, valid_idx = train_test_split(
        dev_idx,
        test_size=0.25,
        stratify=y.iloc[dev_idx],
        random_state=RANDOM_SEED,
    )
    X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
    X_valid, y_valid = X.iloc[valid_idx], y.iloc[valid_idx]
    X_test, y_test = X.iloc[test_idx], y.iloc[test_idx]

    preprocessing_scaled = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())])
    logistic = Pipeline(
        [
            ("preprocess", preprocessing_scaled),
            ("model", LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000, random_state=RANDOM_SEED)),
        ]
    )
    dummy = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("model", DummyClassifier(strategy="prior", random_state=RANDOM_SEED)),
        ]
    )
    forest_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=260,
                    class_weight="balanced",
                    random_state=RANDOM_SEED,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    grid = GridSearchCV(
        forest_pipeline,
        param_grid={
            "model__max_depth": [4, 7, None],
            "model__min_samples_leaf": [2, 5],
            "model__max_features": ["sqrt", 0.8],
        },
        scoring="f1",
        cv=StratifiedKFold(n_splits=4, shuffle=True, random_state=RANDOM_SEED),
        n_jobs=-1,
        refit=True,
    )

    candidates: dict[str, Any] = {"DummyClassifier": dummy, "LogisticRegression": logistic}
    for model in candidates.values():
        model.fit(X_train, y_train)
    grid.fit(X_train, y_train)
    candidates["RandomForest(GridSearchCV)"] = grid.best_estimator_

    validation: dict[str, dict[str, Any]] = {}
    for name, model in candidates.items():
        probability = model.predict_proba(X_valid)[:, 1]
        validation[name] = _metrics(y_valid, probability, 0.5)
    eligible = [name for name in candidates if name != "DummyClassifier"]
    selected_name = max(eligible, key=lambda name: (validation[name]["f1"], validation[name]["roc_auc"]))
    selected_model = candidates[selected_name]
    valid_probability = selected_model.predict_proba(X_valid)[:, 1]
    threshold, threshold_f1 = _best_threshold(y_valid, valid_probability)

    test_probability = selected_model.predict_proba(X_test)[:, 1]
    test_metrics = _metrics(y_test, test_probability, threshold)
    fpr, tpr, _ = roc_curve(y_test, test_probability)

    permutation = permutation_importance(
        selected_model,
        X_test,
        y_test,
        scoring="f1",
        n_repeats=25,
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )
    raw_importance = np.maximum(permutation.importances_mean, 0)
    if float(raw_importance.sum()) == 0:
        raw_importance = np.ones(len(FEATURE_COLUMNS))
    normalised_importance = raw_importance / raw_importance.sum()
    importance = {feature: float(value) for feature, value in zip(FEATURE_COLUMNS, normalised_importance)}
    directions = {
        feature: (1 if float(pd.concat([X_train[feature], y_train.rename("target")], axis=1).corr(method="spearman").iloc[0, 1]) >= 0 else -1)
        for feature in FEATURE_COLUMNS
    }
    medians = {feature: float(X_train[feature].median()) for feature in FEATURE_COLUMNS}
    iqrs = {
        feature: float(max(X_train[feature].quantile(0.75) - X_train[feature].quantile(0.25), 1e-6))
        for feature in FEATURE_COLUMNS
    }

    # После независимой оценки переобучаем выбранную конфигурацию на train+validation.
    production_model = clone(selected_model)
    production_model.fit(X.iloc[dev_idx], y.iloc[dev_idx])
    all_probability = production_model.predict_proba(X)[:, 1]
    created_at = datetime.now(timezone.utc).isoformat()
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"

    artifact = {
        "model": production_model,
        "features": FEATURE_COLUMNS,
        "threshold": threshold,
        "algorithm": selected_name,
        "trained_at": created_at,
        "feature_importance": importance,
        "risk_directions": directions,
        "feature_medians": medians,
        "feature_iqr": iqrs,
        "model_run_id": run_id,
        "synthetic_training_data": True,
    }
    joblib.dump(artifact, MODEL_PATH)

    levels = np.where(all_probability >= 0.65, "Высокий", np.where(all_probability >= 0.35, "Средний", "Низкий"))
    prediction_rows = []
    for pos, (_, row) in enumerate(data.iterrows()):
        factors = _factor_payload(row, importance, directions, medians, iqrs)
        prediction_rows.append(
            {
                "student_id": row["student_id"],
                "model_run_id": run_id,
                "risk_probability": round(float(all_probability[pos]), 6),
                "predicted_at_risk": int(all_probability[pos] >= threshold),
                "risk_level": str(levels[pos]),
                "top_factors": json.dumps(factors, ensure_ascii=False),
                "created_at": created_at,
            }
        )

    connection = connect(db_path)
    try:
        connection.execute(
            """INSERT INTO model_runs
               (model_run_id, created_at, algorithm, threshold, test_f1, test_roc_auc,
                test_recall, dataset_rows, artifact_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                created_at,
                selected_name,
                threshold,
                test_metrics["f1"],
                test_metrics["roc_auc"],
                test_metrics["recall"],
                len(data),
                str(MODEL_PATH.relative_to(PROJECT_ROOT)),
            ),
        )
        pd.DataFrame(prediction_rows).to_sql("predictions", connection, if_exists="append", index=False)
        connection.commit()
    finally:
        connection.close()

    split = pd.DataFrame({"student_id": data["student_id"], "split": "train"})
    split.loc[valid_idx, "split"] = "validation"
    split.loc[test_idx, "split"] = "test"
    split.to_csv(PROCESSED_DIR / "split_assignments.csv", index=False, encoding="utf-8-sig")
    test_output = data.iloc[test_idx][["student_id", "group_name", "at_risk"]].copy()
    test_output["risk_probability"] = test_probability
    test_output["prediction"] = (test_probability >= threshold).astype(int)
    test_output.to_csv(PROCESSED_DIR / "test_predictions.csv", index=False, encoding="utf-8-sig")

    importance_table = pd.DataFrame(
        [
            {
                "feature": feature,
                "label_ru": FEATURE_LABELS_RU[feature],
                "importance": importance[feature],
                "risk_direction": directions[feature],
            }
            for feature in FEATURE_COLUMNS
        ]
    ).sort_values("importance", ascending=False)
    importance_table.to_csv(MODEL_DIR / "feature_importance.csv", index=False, encoding="utf-8-sig")

    metrics: dict[str, Any] = {
        "created_at": created_at,
        "model_run_id": run_id,
        "dataset": {
            "rows": len(data),
            "features": len(FEATURE_COLUMNS),
            "risk_rate": round(float(y.mean()), 4),
            "train_rows": len(train_idx),
            "validation_rows": len(valid_idx),
            "test_rows": len(test_idx),
            "seed": RANDOM_SEED,
        },
        "validation": validation,
        "random_forest_search": {
            "best_params": grid.best_params_,
            "best_cv_f1": round(float(grid.best_score_), 4),
            "combinations": len(grid.cv_results_["params"]),
            "cv_folds": 4,
        },
        "selected_model": selected_name,
        "selection_rule": "максимальный F1 на validation, ROC-AUC как дополнительный критерий",
        "threshold": threshold,
        "validation_f1_at_selected_threshold": threshold_f1,
        "test": test_metrics,
        "roc_curve": {"fpr": [round(float(x), 6) for x in fpr], "tpr": [round(float(x), 6) for x in tpr]},
        "feature_importance": importance_table.to_dict(orient="records"),
    }
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    cm = test_metrics["confusion_matrix"]
    model_card = f"""# Карточка модели академического риска

## Назначение

Модель раннего предупреждения оценивает вероятность академического риска до итоговой аттестации. Она предназначена для приоритизации педагогической поддержки, а не для автоматического назначения санкций или отчисления.

## Версия

- Запуск: `{run_id}`
- Алгоритм: **{selected_name}**
- Порог решения: **{threshold:.2f}**
- Данные: полностью синтетические, {len(data)} студентов, seed={RANDOM_SEED}

## Качество на отложенной тестовой выборке

| Метрика | Значение |
|---|---:|
| F1 | {test_metrics['f1']:.3f} |
| Recall | {test_metrics['recall']:.3f} |
| Precision | {test_metrics['precision']:.3f} |
| ROC-AUC | {test_metrics['roc_auc']:.3f} |
| Average precision | {test_metrics['average_precision']:.3f} |
| Brier score | {test_metrics['brier']:.3f} |

Матрица ошибок `[[TN, FP], [FN, TP]]`: `{cm}`.

## Признаки и предотвращение утечки

Используются только признаки, доступные до экзамена: посещаемость, активность LMS, промежуточные баллы и исторический GPA. Итоговые оценки, число провалов и итоговый GPA применяются только для формирования целевой переменной и исключены из входа модели.

## Ограничения

1. Синтетическая выборка демонстрирует технологию, но не подтверждает применимость к реальному вузу.
2. Вероятность является оценкой риска, а не доказательством будущего результата.
3. Перед пилотом необходимы внешняя валидация, проверка дрейфа, справедливости между группами и правовое основание обработки данных.
4. Решение о вмешательстве принимает человек; студенту должна быть доступна процедура исправления ошибочных данных.
"""
    MODEL_CARD_PATH.write_text(model_card, encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Обучение модели риска")
    parser.add_argument("--dataset", type=Path, default=PROCESSED_DIR / "model_dataset.csv")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    metrics = train_model(args.dataset, args.db)
    print(json.dumps({"selected_model": metrics["selected_model"], "threshold": metrics["threshold"], "test": metrics["test"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
