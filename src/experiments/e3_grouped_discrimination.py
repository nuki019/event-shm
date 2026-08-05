"""Grouped record-level audit of the E3 event-structure discriminator.

The original E3 score used ordinary stratified folds.  This audit keeps the
healthy and damaged records at the same temperature-order index in the same
fold, preventing their shared temperature position from being split between
training and test folds.  It reports D04, D24, and their combined result.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.experiments.e3_final import feats


PROC = Path("data/processed")
OUT = Path("results/e3_grouped_discrimination.json")
DELTA = 0.004


def feature_matrix(residuals: np.ndarray) -> np.ndarray:
    return np.array([feats(record, DELTA) for record in residuals], dtype=np.float64)


def evaluate(healthy: np.ndarray, damaged_sets: list[tuple[str, np.ndarray]]) -> dict:
    healthy_x = feature_matrix(healthy)
    damaged_x = [(name, feature_matrix(data)) for name, data in damaged_sets]
    x = np.vstack((healthy_x, *(data for _, data in damaged_x)))
    y = np.concatenate((np.zeros(len(healthy_x), dtype=int), *(np.ones(len(data), dtype=int) for _, data in damaged_x)))
    groups = np.concatenate((np.arange(len(healthy_x)), *(np.arange(len(data)) for _, data in damaged_x)))
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    probabilities = cross_val_predict(
        model,
        x,
        y,
        cv=GroupKFold(n_splits=5),
        groups=groups,
        method="predict_proba",
    )[:, 1]

    result = {
        "n_healthy": int(len(healthy_x)),
        "n_damaged": int(sum(len(data) for _, data in damaged_x)),
        "grouped_cv_auc_combined": float(roc_auc_score(y, probabilities)),
        "per_damage": {},
        "single_feature_auc_absolute_direction": {},
    }
    cursor = len(healthy_x)
    for name, data in damaged_x:
        stop = cursor + len(data)
        index = np.concatenate((np.arange(len(healthy_x)), np.arange(cursor, stop)))
        local_y = y[index]
        local_x = x[index]
        result["per_damage"][name] = float(roc_auc_score(local_y, probabilities[index]))
        for column, feature_name in enumerate(
            ("coherence", "localization", "event_count", "arrival_std", "active_path_fraction")
        ):
            auc = roc_auc_score(local_y, local_x[:, column])
            result["single_feature_auc_absolute_direction"].setdefault(feature_name, {})[name] = float(max(auc, 1.0 - auc))
        cursor = stop
    return result


def main() -> None:
    healthy = np.load(PROC / "R_udam_f40.npy", mmap_mode="r")
    damaged_sets = [
        ("D04", np.load(PROC / "R_D04_f40.npy", mmap_mode="r")),
        ("D24", np.load(PROC / "R_D24_f40.npy", mmap_mode="r")),
    ]
    payload = {
        "protocol": {
            "unit_of_analysis": "record",
            "frequency_khz": 40,
            "sod_delta": DELTA,
            "split": "5-fold GroupKFold grouped by temperature-order index across conditions",
            "features": ["coherence", "localization", "event_count", "arrival_std", "active_path_fraction"],
            "caveat": "Both classes come from the same OGW plate and campaign family; grouping reduces within-temperature leakage but is not independent-structure validation.",
        },
        "result": evaluate(healthy, damaged_sets),
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    result = payload["result"]
    print(f"grouped-CV combined AUC: {result['grouped_cv_auc_combined']:.3f}")
    for name, auc in result["per_damage"].items():
        print(f"  {name}: {auc:.3f}")
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
