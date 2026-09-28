from __future__ import annotations

import joblib
import pandas as pd

from src.config import FEATURE_COLUMNS, MODEL_PATH, PROCESSED_DIR


def test_saved_model_predicts_probabilities() -> None:
    artifact = joblib.load(MODEL_PATH)
    frame = pd.read_csv(PROCESSED_DIR / "model_dataset.csv", encoding="utf-8-sig")
    probability = artifact["model"].predict_proba(frame[FEATURE_COLUMNS].head(8))[:, 1]
    assert len(probability) == 8
    assert ((probability >= 0) & (probability <= 1)).all()
    assert artifact["features"] == FEATURE_COLUMNS
