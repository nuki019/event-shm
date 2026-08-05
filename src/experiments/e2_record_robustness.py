"""Record-level robustness audit for the 40-kHz OGW SoD experiment.

This script is deliberately separate from the exploratory E2 scripts.  It
evaluates one score per *record* (not one score per path), fixes the SoD
threshold grid before scoring, and reports controlled additive-noise results
with a fixed seed.  Thus the 66 paths in a record are aggregated rather than
treated as independent observations.

Inputs are the reproducible OBS+BSS residual caches produced by
``cache_residuals.py``.  The protocol is restricted to the 40 cached records
per condition and the D04/D24 reversible-disc cases; it does not claim
cross-structure or hardware-deployment validation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


PROC = Path("data/processed")
OUT = Path("results/e2_record_robustness.json")
DEFAULT_DELTAS = (0.003, 0.0045, 0.006, 0.009, 0.013)
DEFAULT_NOISE_DB = (None, 30.0, 20.0, 10.0)
SEED = 20260728


def sod_energy_and_count(x: np.ndarray, delta: float) -> tuple[float, int]:
    """Return zero-order-hold reconstruction energy and SoD event count.

    With initial level zero, the decoder in :mod:`src.methods.sod` reconstructs
    exactly ``q * delta`` at each sample, where ``q`` is the quantized signal.
    Therefore its energy is ``delta**2 * sum(q**2)``; calculating it directly
    avoids creating repeated events or a full reconstructed signal.
    """

    q = np.floor(np.asarray(x, dtype=np.float32) / delta + 0.5).astype(np.int64)
    count = int(np.abs(np.diff(np.concatenate(([0], q)))).sum())
    return float(delta * delta * np.dot(q, q)), count


def uniform_zoh_energy(x: np.ndarray, n_samples: int) -> float:
    """Energy of a uniform zero-order-hold reconstruction with ``n_samples``.

    The count matches the number of SoD events on the corresponding path.  It
    is a matched-sample-count representation baseline, not a bit-exact codec:
    uniform timestamps are implicit whereas SoD timestamps must be encoded.
    """

    n_total = len(x)
    if n_samples <= 0:
        return 0.0
    if n_samples >= n_total:
        return float(np.dot(x, x))
    indices = np.unique(np.linspace(0, n_total - 1, n_samples, dtype=np.int64))
    segment_lengths = np.diff(np.concatenate((indices, [n_total])))
    values = np.asarray(x, dtype=np.float64)[indices]
    return float(np.dot(segment_lengths.astype(np.float64), values * values))


def record_scores(
    residuals: np.ndarray,
    delta: float,
    noise_db: float | None,
    rng: np.random.Generator,
    include_uniform: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Aggregate SoD energy, rate, and optional uniform energy by record."""

    n_records, n_paths, n_samples = residuals.shape
    scores = np.empty(n_records, dtype=np.float64)
    rates = np.empty(n_records, dtype=np.float64)
    uniform_scores = np.empty(n_records, dtype=np.float64) if include_uniform else None
    for record_index, record in enumerate(residuals):
        energy = 0.0
        uniform_energy = 0.0
        count = 0
        for x in record:
            if noise_db is not None:
                sigma = float(np.std(x)) / (10.0 ** (noise_db / 20.0))
                x = x + rng.normal(0.0, sigma, size=x.shape).astype(np.float32)
            path_energy, path_count = sod_energy_and_count(x, delta)
            energy += path_energy
            if include_uniform:
                uniform_energy += uniform_zoh_energy(x, path_count)
            count += path_count
        scores[record_index] = energy / n_paths
        rates[record_index] = count / (n_paths * n_samples)
        if include_uniform:
            uniform_scores[record_index] = uniform_energy / n_paths
    return scores, rates, uniform_scores


def paired_win_rate(healthy: np.ndarray, damaged: np.ndarray) -> float:
    """Temperature-order paired win rate, reported separately from ROC AUC."""

    if len(healthy) != len(damaged):
        raise ValueError("paired evaluation requires equal record counts")
    return float(np.mean(damaged > healthy))


def evaluate_case(
    healthy: np.ndarray,
    damaged: np.ndarray,
    damage_name: str,
    deltas: tuple[float, ...],
    noise_levels: tuple[float | None, ...],
) -> dict:
    labels = np.concatenate((np.zeros(len(healthy), dtype=int), np.ones(len(damaged), dtype=int)))
    rows: list[dict] = []
    for delta in deltas:
        for noise_db in noise_levels:
            rng = np.random.default_rng(SEED)
            include_uniform = noise_db is None
            healthy_scores, healthy_rates, healthy_uniform = record_scores(
                healthy, delta, noise_db, rng, include_uniform
            )
            damaged_scores, damaged_rates, damaged_uniform = record_scores(
                damaged, delta, noise_db, rng, include_uniform
            )
            scores = np.concatenate((healthy_scores, damaged_scores))
            row = {
                "delta": float(delta),
                "noise_snr_db": None if noise_db is None else float(noise_db),
                "record_auc": float(roc_auc_score(labels, scores)),
                "temperature_order_paired_win_rate": paired_win_rate(healthy_scores, damaged_scores),
                "event_rate_all": float(np.mean(np.concatenate((healthy_rates, damaged_rates)))),
                "event_rate_healthy": float(np.mean(healthy_rates)),
                "event_rate_damaged": float(np.mean(damaged_rates)),
            }
            if include_uniform:
                uniform_scores = np.concatenate((healthy_uniform, damaged_uniform))
                row["uniform_zoh_matched_count_auc"] = float(roc_auc_score(labels, uniform_scores))
            rows.append(row)
    return {"damage": damage_name, "n_records_per_class": int(len(healthy)), "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--deltas", type=float, nargs="+", default=DEFAULT_DELTAS)
    parser.add_argument(
        "--noise-db",
        type=float,
        nargs="*",
        default=(20.0, 10.0),
        help="Additive white-noise SNR values; clean is always included.",
    )
    args = parser.parse_args()

    healthy = np.load(PROC / "R_udam_f40.npy", mmap_mode="r")
    cases = []
    noise_levels = (None, *tuple(args.noise_db))
    for damage_name in ("D04", "D24"):
        damaged = np.load(PROC / f"R_{damage_name}_f40.npy", mmap_mode="r")
        cases.append(evaluate_case(healthy, damaged, damage_name, tuple(args.deltas), noise_levels))

    payload = {
        "protocol": {
            "unit_of_analysis": "record; each score aggregates all 66 paths",
            "frequency_khz": 40,
            "residual_source": "cached high-pass, unit-energy-normalized OBS+BSS residuals",
            "comparison_scope": "within OGW CFRP, D04/D24 reversible surface discs only",
            "noise": "independent additive white Gaussian noise per path; fixed seed",
            "seed": SEED,
            "caveat": "This is not a cross-structure, field-noise, or embedded-hardware evaluation.",
        },
        "cases": cases,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    for case in cases:
        print(f"{case['damage']} ({case['n_records_per_class']} records/class)")
        for row in case["rows"]:
            noise = "clean" if row["noise_snr_db"] is None else f"{row['noise_snr_db']:g} dB"
            print(
                f"  delta={row['delta']:.4g} noise={noise:>6} "
                f"rate={row['event_rate_all']:.6g} "
                f"AUC={row['record_auc']:.3f} "
                f"paired-win={row['temperature_order_paired_win_rate']:.3f}"
            )
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
