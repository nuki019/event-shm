"""Frozen cross-month cold-start alarm evaluation for the long-term dataset.

The complete healthy month 2021_03 supplies every baseline, event threshold,
normalization statistic, and alarm threshold.  The future month 2021_04 is
then replayed once without recalibration.  Its labels are consumed only after
scores have been computed, to report false calls/day and the outcome for its
single labelled onset.

This is software replay, not MCU or power validation.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.longterm_loader import load_month
from src.methods.baseline_fast import stretch_batch
from src.methods.strict_alarm import (
    RobustScoreModel,
    evaluate_alarm_threshold,
    frozen_threshold_grid,
    temperature_support_distance,
)


PROTOCOL_PATH = ROOT / "protocols" / "strict_evaluation_v1.json"
DEFAULT_CACHE_DIR = ROOT / "data" / "interim" / "strict_alarm_v1"
DEFAULT_OUTPUT = ROOT / "results" / "e8_cold_start_alarm_v1.json"
DEFAULT_PLOT = ROOT / "figures" / "e8_cold_start_alarm_v1.png"


def _load_protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def _normalize_paths(record: np.ndarray) -> np.ndarray:
    record = np.asarray(record, dtype=np.float32)
    norms = np.sqrt(np.einsum("ij,ij->i", record, record))[:, None] + 1e-12
    return record / norms


def _temperature_stratified_reference_indices(
    temperatures: np.ndarray,
    bin_width: float,
    prototypes_per_bin: int,
) -> np.ndarray:
    """Choose chronological prototypes within each fixed-width temperature bin."""

    bin_ids = np.floor(np.asarray(temperatures, dtype=float) / bin_width).astype(int)
    selected: list[int] = []
    for bin_id in sorted(np.unique(bin_ids)):
        indices = np.flatnonzero(bin_ids == bin_id)
        count = min(prototypes_per_bin, len(indices))
        positions = np.rint(np.linspace(0, len(indices) - 1, count)).astype(int)
        selected.extend(indices[positions].tolist())
    return np.asarray(sorted(set(selected)), dtype=int)


def _nearest_reference_positions(
    reference_temperatures: np.ndarray,
    target_temperature: float,
    count: int,
    excluded_source_index: int | None,
    reference_source_indices: np.ndarray,
) -> np.ndarray:
    order = np.argsort(np.abs(reference_temperatures - target_temperature), kind="stable")
    if excluded_source_index is not None:
        order = order[reference_source_indices[order] != excluded_source_index]
    if len(order) < count:
        raise RuntimeError("fewer reference candidates than the frozen candidate count")
    return order[:count]


def _obs_bss_residual(
    signal: np.ndarray,
    candidate_bank: np.ndarray,
    alphas: np.ndarray,
) -> np.ndarray:
    """Select a temperature-near OBS+BSS baseline for all paths together."""

    candidates, paths, samples = candidate_bank.shape
    best_energy = np.full(paths, np.inf, dtype=np.float64)
    best_residual = np.empty_like(signal, dtype=np.float32)
    path_index = np.arange(paths)
    for alpha in alphas:
        stretched = stretch_batch(candidate_bank.reshape(-1, samples), float(alpha)).reshape(candidates, paths, samples)
        residuals = signal[None, :, :] - stretched
        energy = np.einsum("kpn,kpn->kp", residuals, residuals)
        choice = np.argmin(energy, axis=0)
        chosen_energy = energy[choice, path_index]
        improved = chosen_energy < best_energy
        if np.any(improved):
            best_residual[improved] = residuals[choice[improved], path_index[improved]]
            best_energy[improved] = chosen_energy[improved]
    return best_residual


def _month_selection(month: str, data: dict[str, Any], smoke: bool, predeclared_onset: int | None = None) -> np.ndarray:
    if not smoke:
        return np.arange(len(data["temp"]), dtype=int)
    if month == "2021_03":
        return np.arange(min(128, len(data["temp"])), dtype=int)
    if predeclared_onset is None:
        raise ValueError("smoke target month requires a protocol-declared onset index")
    if not 0 <= predeclared_onset < len(data["temp"]):
        raise ValueError("protocol-declared onset index lies outside the target month")
    prefix = np.arange(min(32, predeclared_onset), dtype=int)
    suffix = np.arange(predeclared_onset, min(predeclared_onset + 32, len(data["temp"])), dtype=int)
    return np.concatenate((prefix, suffix))


def _cached_paths(cache_dir: Path, prefix: str) -> dict[str, Path]:
    return {
        "residuals": cache_dir / f"{prefix}_residuals.npy",
        "temperatures": cache_dir / f"{prefix}_temperatures.npy",
        "times": cache_dir / f"{prefix}_times.npy",
        "source_indices": cache_dir / f"{prefix}_source_indices.npy",
        "complete": cache_dir / f"{prefix}_complete.json",
    }


def _cache_residual_month(
    cache_dir: Path,
    prefix: str,
    data: dict[str, Any],
    source_indices: np.ndarray,
    reference_bank: np.ndarray,
    reference_temperatures: np.ndarray,
    reference_source_indices: np.ndarray,
    candidate_count: int,
    alphas: np.ndarray,
    leave_self_out: bool,
    force: bool,
) -> dict[str, Path]:
    paths = _cached_paths(cache_dir, prefix)
    expected_shape = (len(source_indices), data["gw"].shape[1], data["gw"].shape[2])
    required_data_paths = (paths["residuals"], paths["temperatures"], paths["times"], paths["source_indices"])
    if not force and all(path.exists() for path in paths.values()):
        residuals = np.load(paths["residuals"], mmap_mode="r")
        cached_indices = np.load(paths["source_indices"])
        try:
            completion = json.loads(paths["complete"].read_text(encoding="utf-8"))
            newest_data_mtime = max(path.stat().st_mtime for path in required_data_paths)
            cache_complete = paths["complete"].stat().st_mtime >= newest_data_mtime
        except (OSError, json.JSONDecodeError):
            completion, cache_complete = {}, False
        if (
            residuals.shape == expected_shape
            and np.array_equal(cached_indices, source_indices)
            and cache_complete
            and completion == {
                "schema": "e8-residual-cache-v1",
                "prefix": prefix,
                "source_indices": source_indices.tolist(),
                "reference_source_indices": reference_source_indices.tolist(),
                "candidate_count": candidate_count,
                "alphas": alphas.tolist(),
                "leave_self_out": leave_self_out,
            }
        ):
            return paths

    cache_dir.mkdir(parents=True, exist_ok=True)
    output = np.lib.format.open_memmap(paths["residuals"], mode="w+", dtype=np.float32, shape=expected_shape)
    for local_index, source_index in enumerate(source_indices):
        candidate_positions = _nearest_reference_positions(
            reference_temperatures,
            float(data["temp"][source_index]),
            candidate_count,
            int(source_index) if leave_self_out else None,
            reference_source_indices,
        )
        signal = _normalize_paths(data["gw"][source_index])
        output[local_index] = _obs_bss_residual(signal, reference_bank[candidate_positions], alphas)
        if (local_index + 1) % 100 == 0 or local_index + 1 == len(source_indices):
            print(f"cached {prefix}: {local_index + 1}/{len(source_indices)}", flush=True)
    del output
    np.save(paths["temperatures"], np.asarray(data["temp"])[source_indices])
    np.save(paths["times"], np.asarray(data["t"])[source_indices].astype("datetime64[s]"))
    np.save(paths["source_indices"], source_indices)
    # Write completion metadata last so an interrupted cache is recomputed.
    paths["complete"].write_text(
        json.dumps(
            {
                "schema": "e8-residual-cache-v1",
                "prefix": prefix,
                "source_indices": source_indices.tolist(),
                "reference_source_indices": reference_source_indices.tolist(),
                "candidate_count": candidate_count,
                "alphas": alphas.tolist(),
                "leave_self_out": leave_self_out,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return paths


def _event_deltas(calibration_residuals: np.ndarray, protocol: dict[str, Any]) -> np.ndarray:
    spec = protocol["cold_start_alarm"]["level_a_event_count"]
    stride = int(spec["sample_stride"])
    quantile = float(spec["delta_quantile"])
    deltas = np.empty(calibration_residuals.shape[1], dtype=np.float64)
    for path in range(calibration_residuals.shape[1]):
        sampled = np.abs(np.asarray(calibration_residuals[:, path, ::stride], dtype=np.float32)).ravel()
        deltas[path] = float(np.quantile(sampled, quantile))
    if np.any(~np.isfinite(deltas)) or np.any(deltas <= 0):
        raise RuntimeError("calibration produced invalid Level-A thresholds")
    return deltas


def _features_from_residuals(residuals: np.ndarray, deltas: np.ndarray, chunk_records: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """Return dense residual energy and Level-A SoD event count per path."""

    records, paths, _ = residuals.shape
    dense = np.empty((records, paths), dtype=np.float64)
    events = np.empty((records, paths), dtype=np.float64)
    for start in range(0, records, chunk_records):
        stop = min(records, start + chunk_records)
        block = np.asarray(residuals[start:stop], dtype=np.float32)
        dense[start:stop] = np.einsum("rpn,rpn->rp", block, block)
        levels = np.rint(block / deltas[None, :, None]).astype(np.int32)
        events[start:stop] = np.abs(np.diff(levels, axis=2)).sum(axis=2)
    return dense, events


def _temperature_support(calibration_temperatures: np.ndarray, target_temperatures: np.ndarray) -> dict[str, Any]:
    distance = temperature_support_distance(calibration_temperatures, target_temperatures)
    lower = float(np.min(calibration_temperatures))
    upper = float(np.max(calibration_temperatures))
    outside = (target_temperatures < lower) | (target_temperatures > upper)
    return {
        "calibration_range_celsius": [lower, upper],
        "target_outside_range_records": int(np.sum(outside)),
        "target_outside_range_fraction": float(np.mean(outside)),
        "nearest_calibration_temperature_distance_celsius": {
            "median": float(np.median(distance)),
            "p95": float(np.quantile(distance, 0.95)),
            "maximum": float(np.max(distance)),
        },
    }


def _plot_alarm_curves(results: dict[str, Any], output: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    labels = {
        "dense_residual_energy": "Dense residual energy",
        "level_a_sod_event_count": "Level-A SoD count",
    }
    for feature_name, feature_results in results["feature_results"].items():
        curve = feature_results["blind_test_curve"]
        rates = [entry["false_calls_per_day"] for entry in curve]
        delays = [entry["first_post_onset_delay_minutes"] for entry in curve]
        coverage = [entry["post_onset_record_exceedance_coverage"] for entry in curve]
        valid_delay = sorted((rate, delay) for rate, delay in zip(rates, delays) if delay is not None)
        coverage_points = sorted(zip(rates, coverage))
        if valid_delay:
            axes[0].scatter(
                [pair[0] for pair in valid_delay],
                [pair[1] for pair in valid_delay],
                label=labels.get(feature_name, feature_name),
            )
        axes[1].scatter(
            [pair[0] for pair in coverage_points],
            [pair[1] for pair in coverage_points],
            label=labels.get(feature_name, feature_name),
        )
    axes[0].set_xlabel("false calls/day on April healthy prefix")
    axes[0].set_ylabel("first post-onset alarm delay (minutes)")
    axes[1].set_xlabel("false calls/day on April healthy prefix")
    axes[1].set_ylabel("post-onset record exceedance coverage")
    for axis in axes:
        axis.grid(True, alpha=0.25)
        axis.legend(fontsize=8)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def run(args: argparse.Namespace) -> dict[str, Any]:
    protocol = _load_protocol()
    alarm = protocol["cold_start_alarm"]
    cache_dir = args.cache_dir
    calibration_month = alarm["calibration_month"]
    test_month = alarm["blind_test_month"]

    calibration = load_month(calibration_month)
    if np.any(np.asarray(calibration["damage"]) != 0):
        raise RuntimeError(f"{calibration_month} is not a fully healthy calibration month")
    calibration_indices = _month_selection(calibration_month, calibration, args.smoke)
    bank_spec = alarm["reference_bank"]
    reference_indices = _temperature_stratified_reference_indices(
        np.asarray(calibration["temp"])[calibration_indices],
        float(bank_spec["temperature_bin_celsius"]),
        int(bank_spec["prototypes_per_nonempty_bin"]),
    )
    reference_indices = calibration_indices[reference_indices]
    reference_bank = np.stack([_normalize_paths(calibration["gw"][index]) for index in reference_indices])
    reference_temperatures = np.asarray(calibration["temp"])[reference_indices]
    alphas = np.asarray(bank_spec["stretch_factors"], dtype=np.float64)
    calibration_cache = _cache_residual_month(
        cache_dir,
        "smoke_2021_03" if args.smoke else "2021_03",
        calibration,
        calibration_indices,
        reference_bank,
        reference_temperatures,
        reference_indices,
        int(bank_spec["nearest_temperature_candidates"]),
        alphas,
        bool(bank_spec["leave_self_out_when_scoring_calibration"]),
        args.force_cache,
    )
    calibration_residuals = np.load(calibration_cache["residuals"], mmap_mode="r")
    deltas = _event_deltas(calibration_residuals, protocol)
    calibration_dense, calibration_events = _features_from_residuals(calibration_residuals, deltas)
    calibration_temperatures = np.load(calibration_cache["temperatures"])
    del calibration
    gc.collect()

    target = load_month(test_month)
    predeclared_onset = int(alarm["test_label_change_record"])
    target_indices = _month_selection(test_month, target, args.smoke, predeclared_onset)
    target_cache = _cache_residual_month(
        cache_dir,
        "smoke_2021_04" if args.smoke else "2021_04",
        target,
        target_indices,
        reference_bank,
        reference_temperatures,
        reference_indices,
        int(bank_spec["nearest_temperature_candidates"]),
        alphas,
        False,
        args.force_cache,
    )
    target_residuals = np.load(target_cache["residuals"], mmap_mode="r")
    target_dense, target_events = _features_from_residuals(target_residuals, deltas)
    target_temperatures = np.load(target_cache["temperatures"])
    target_times = np.load(target_cache["times"])

    feature_pairs = {
        "dense_residual_energy": (calibration_dense, target_dense),
        "level_a_sod_event_count": (calibration_events, target_events),
    }
    frozen_replay: dict[str, dict[str, Any]] = {}
    for feature_name, (calibration_feature, target_feature) in feature_pairs.items():
        score_model = RobustScoreModel.fit(calibration_feature)
        calibration_scores = score_model.score(calibration_feature)
        target_scores = score_model.score(target_feature)
        thresholds = frozen_threshold_grid(calibration_scores)
        frozen_replay[feature_name] = {
            "score_model": score_model,
            "calibration_scores": calibration_scores,
            "target_scores": target_scores,
            "thresholds": thresholds,
        }

    # The blind replay is fully scored before this single label access.  The
    # labels identify exposure and the already protocol-declared onset only.
    target_labels = np.asarray(target["damage"])[target_indices]
    observed_onsets = np.flatnonzero(target_labels > 0)
    if not len(observed_onsets):
        raise RuntimeError("the blind target subset contains no labelled transition")
    observed_source_index = int(target_indices[observed_onsets[0]])
    if observed_source_index != predeclared_onset:
        raise RuntimeError(
            f"protocol onset {predeclared_onset} disagrees with target labels at source index {observed_source_index}"
        )

    feature_results: dict[str, Any] = {}
    for feature_name, replay in frozen_replay.items():
        score_model = replay["score_model"]
        calibration_scores = replay["calibration_scores"]
        target_scores = replay["target_scores"]
        thresholds = replay["thresholds"]
        curve = [
            evaluate_alarm_threshold(
                target_times,
                target_labels,
                target_scores,
                threshold,
                int(alarm["incident_dedup_minutes"]),
            )
            for threshold in thresholds
        ]
        feature_results[feature_name] = {
            "calibration_score_summary": {
                "median": float(np.median(calibration_scores)),
                "p95": float(np.quantile(calibration_scores, 0.95)),
                "maximum": float(np.max(calibration_scores)),
            },
            "robust_score_model": {
                "median_per_path": score_model.median.tolist(),
                "mad_scale_per_path": score_model.mad_scale.tolist(),
            },
            "thresholds_from_2021_03_only": thresholds.tolist(),
            "blind_test_curve": curve,
        }
        print(
            f"{feature_name}: {len(curve)} frozen thresholds; "
            f"lowest false-call rate={min(entry['false_calls_per_day'] for entry in curve):.3f}/day",
            flush=True,
        )

    del target
    gc.collect()

    output = {
        "protocol_id": protocol["protocol_id"],
        "smoke": bool(args.smoke),
        "system_boundary": alarm["system_boundary"],
        "calibration_month": calibration_month,
        "blind_test_month": test_month,
        "calibration_records": int(len(calibration_indices)),
        "blind_test_records": int(len(target_indices)),
        "reference_bank": {
            "source_indices": reference_indices.tolist(),
            "temperatures": reference_temperatures.tolist(),
            "count": int(len(reference_indices)),
            "nearest_candidates": int(bank_spec["nearest_temperature_candidates"]),
            "stretch_factors": alphas.tolist(),
        },
        "level_a_deltas_from_2021_03_only": deltas.tolist(),
        "temperature_support": _temperature_support(calibration_temperatures, target_temperatures),
        "test_label_metadata": {
            "protocol_declared_source_index": predeclared_onset,
            "first_nonzero_label_local_index": int(observed_onsets[0]),
            "first_nonzero_label_time": str(target_times[observed_onsets[0]]),
            "blind_replay_completed_before_label_evaluation": True,
            "smoke_selection_note": "Smoke mode uses the protocol-declared onset index only to exercise reporting; it is not an evidentiary subset." if args.smoke else None,
            "note": "One observed labelled transition is reported as an outcome, not as a population probability of detection.",
        },
        "feature_results": feature_results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    _plot_alarm_curves(output, args.plot)
    print(f"saved {args.output}")
    print(f"saved {args.plot}")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="Cache a small calibration/test subset to validate the complete pipeline.")
    parser.add_argument("--force-cache", action="store_true", help="Recompute cached residual arrays.")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plot", type=Path, default=DEFAULT_PLOT)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
