"""Strict, byte-accounted post-compensation codec benchmark.

This replaces exploratory sample-rate comparisons with a frozen protocol:

* all residual/codec fitting uses healthy training dates only;
* codec operating points are selected from healthy validation payload only;
* D04/D24 labels are read only for final held-out metrics;
* actual serialized packet bytes, not event counts, define the rate axis.

The experiment deliberately evaluates post-compensation waveform coding.  It
does not claim that offline residual replay measures ADC acquisition energy or
embedded execution cost.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.signal import butter, filtfilt
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.ogw_loader import OGWSetZip
from src.methods.baseline_fast import stretch_batch
from src.methods.strict_codecs import (
    HaarDwtCodec,
    Int16SignalQuantizer,
    PcaCodec,
    PcaModel,
    RecordCodec,
    SodTransitionCodec,
    UniformLinearCodec,
    encode_uvarint,
    fit_haar_scale,
    next_power_of_two,
)


PROTOCOL_PATH = ROOT / "protocols" / "strict_evaluation_v1.json"
DEFAULT_CACHE_DIR = ROOT / "data" / "interim" / "strict_codec_v1"
DEFAULT_OUTPUT = ROOT / "results" / "e7_strict_codec_benchmark_v1.json"
DEFAULT_PLOT = ROOT / "figures" / "e7_strict_codec_benchmark_v1.png"
SEED = 20260729
FREQUENCY_KHZ = 40
HIGH_PASS = butter(3, 20e3 / 5e6, btype="high")


@dataclass(frozen=True)
class CachedSplit:
    name: str
    residual_path: Path
    temperature_path: Path
    source_index_path: Path
    source_dates: list[str]

    def residuals(self) -> np.ndarray:
        return np.load(self.residual_path, mmap_mode="r")

    def temperatures(self) -> np.ndarray:
        return np.load(self.temperature_path)


def _load_protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def _preprocess(signals: np.ndarray) -> np.ndarray:
    filtered = filtfilt(HIGH_PASS[0], HIGH_PASS[1], signals, axis=1).astype(np.float32)
    norms = np.sqrt(np.einsum("ij,ij->i", filtered, filtered))[:, None] + 1e-12
    return filtered / norms


def _temperature_stratified_indices(temperatures: np.ndarray, count: int) -> np.ndarray:
    """Choose a deterministic spread of healthy records over temperature."""

    if count <= 0 or len(temperatures) < count:
        raise ValueError("baseline pool count exceeds available training records")
    order = np.argsort(temperatures, kind="stable")
    positions = np.rint(np.linspace(0, len(order) - 1, count)).astype(int)
    selected = order[positions]
    if len(np.unique(selected)) != count:
        raise RuntimeError("temperature-stratified selection unexpectedly repeated an index")
    return selected


def _obs_bss_residual(
    signal: np.ndarray,
    baseline_pool: np.ndarray,
    alphas: np.ndarray,
    excluded_pool_position: int | None = None,
) -> np.ndarray:
    """Select OBS+BSS residuals for all paths without path-level labels."""

    if excluded_pool_position is not None:
        keep = np.ones(len(baseline_pool), dtype=bool)
        keep[excluded_pool_position] = False
        baselines = baseline_pool[keep]
    else:
        baselines = baseline_pool
    if len(baselines) < 2:
        raise ValueError("at least two candidate baselines are required after leave-one-out exclusion")
    paths, samples = signal.shape
    best_energy = np.full(paths, np.inf, dtype=np.float64)
    best_residual = np.empty_like(signal, dtype=np.float32)
    path_index = np.arange(paths)
    for alpha in alphas:
        stretched = stretch_batch(baselines.reshape(-1, samples), float(alpha)).reshape(len(baselines), paths, samples)
        residuals = signal[None, :, :] - stretched
        energy = np.einsum("kpn,kpn->kp", residuals, residuals)
        candidate_index = np.argmin(energy, axis=0)
        candidate_energy = energy[candidate_index, path_index]
        improved = candidate_energy < best_energy
        if np.any(improved):
            best_residual[improved] = residuals[candidate_index[improved], path_index[improved]]
            best_energy[improved] = candidate_energy[improved]
    return best_residual


def _source_dates(dataset: OGWSetZip) -> np.ndarray:
    return np.asarray([folder[:8] for folder in dataset.folder_list])


def _cache_dataset(
    cache_dir: Path,
    name: str,
    dataset: OGWSetZip,
    source_indices: np.ndarray,
    baseline_pool: np.ndarray,
    baseline_source_indices: np.ndarray,
    alphas: np.ndarray,
    force: bool,
) -> CachedSplit:
    """Cache compensation residuals without ever reading labels for a split."""

    residual_path = cache_dir / f"{name}_residuals.npy"
    temperature_path = cache_dir / f"{name}_temperatures.npy"
    source_index_path = cache_dir / f"{name}_source_indices.npy"
    complete_path = cache_dir / f"{name}_complete.json"
    dates = _source_dates(dataset)[source_indices].tolist()
    expected_shape = (len(source_indices), 66, 13108)
    if not force and residual_path.exists() and temperature_path.exists() and source_index_path.exists() and complete_path.exists():
        existing = np.load(residual_path, mmap_mode="r")
        existing_indices = np.load(source_index_path)
        try:
            completion = json.loads(complete_path.read_text(encoding="utf-8"))
            newest_data_mtime = max(path.stat().st_mtime for path in (residual_path, temperature_path, source_index_path))
            cache_complete = complete_path.stat().st_mtime >= newest_data_mtime
        except (OSError, json.JSONDecodeError):
            completion, cache_complete = {}, False
        if (
            existing.shape == expected_shape
            and np.array_equal(existing_indices, source_indices)
            and cache_complete
            and completion == {
                "schema": "e7-residual-cache-v1",
                "name": name,
                "source_indices": source_indices.tolist(),
                "baseline_source_indices": baseline_source_indices.tolist(),
                "alphas": alphas.tolist(),
            }
        ):
            return CachedSplit(name, residual_path, temperature_path, source_index_path, dates)

    cache_dir.mkdir(parents=True, exist_ok=True)
    temperatures = dataset.temperatures()[source_indices]
    output = np.lib.format.open_memmap(residual_path, mode="w+", dtype=np.float32, shape=expected_shape)
    baseline_lookup = {int(source): position for position, source in enumerate(baseline_source_indices)}
    for local_index, source_index in enumerate(source_indices):
        signal = _preprocess(dataset.signals(int(source_index), FREQUENCY_KHZ))
        output[local_index] = _obs_bss_residual(
            signal,
            baseline_pool,
            alphas,
            baseline_lookup.get(int(source_index)),
        )
        if (local_index + 1) % 10 == 0 or local_index + 1 == len(source_indices):
            print(f"cached {name}: {local_index + 1}/{len(source_indices)}", flush=True)
    del output
    np.save(temperature_path, temperatures)
    np.save(source_index_path, source_indices)
    # This marker is written only after every array is complete.  A partial
    # cache therefore cannot be silently reused after an interrupted run.
    complete_path.write_text(
        json.dumps(
            {
                "schema": "e7-residual-cache-v1",
                "name": name,
                "source_indices": source_indices.tolist(),
                "baseline_source_indices": baseline_source_indices.tolist(),
                "alphas": alphas.tolist(),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return CachedSplit(name, residual_path, temperature_path, source_index_path, dates)


def _split_indices(dataset: OGWSetZip, allowed_dates: list[str], smoke_limit: int | None) -> np.ndarray:
    dates = _source_dates(dataset)
    selected = np.flatnonzero(np.isin(dates, allowed_dates))
    if smoke_limit is not None:
        selected = selected[:smoke_limit]
    if not len(selected):
        raise RuntimeError(f"no records selected for dates {allowed_dates}")
    return selected


def _smoke_temperature_matches(dataset: OGWSetZip, target_temperatures: np.ndarray) -> np.ndarray:
    """Select tiny smoke subsets that still exercise temperature matching."""

    cost = np.abs(target_temperatures[:, None] - dataset.temperatures()[None, :])
    _, columns = linear_sum_assignment(cost)
    return np.sort(columns.astype(int))


def _summarize_payload(values: np.ndarray) -> dict[str, float]:
    values = np.asarray(values, dtype=np.float64)
    return {
        "mean_bytes_per_record": float(np.mean(values)),
        "median_bytes_per_record": float(np.median(values)),
        "p95_bytes_per_record": float(np.quantile(values, 0.95)),
        "maximum_bytes_per_record": float(np.max(values)),
        "mean_bits_per_original_sample": float(np.mean(values) * 8.0 / (66 * 13108)),
    }


def _evaluate_codec(codec: RecordCodec, records: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    scores = np.empty(len(records), dtype=np.float64)
    payload = np.empty(len(records), dtype=np.int64)
    for index, record in enumerate(records):
        scores[index], payload[index] = codec.evaluate_record(record)
    return scores, payload


def _evaluate_selected_pca_targets(
    target_map: dict[int, RecordCodec],
    records: np.ndarray,
) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """Reuse one frozen PCA projection for every selected record-capacity rank."""

    codecs = {target: codec for target, codec in target_map.items() if isinstance(codec, PcaCodec)}
    if len(codecs) != len(target_map):
        raise TypeError("PCA target map contains a non-PCA codec")
    model = next(iter(codecs.values())).model
    if any(codec.model is not model for codec in codecs.values()):
        raise RuntimeError("selected PCA codecs do not share one frozen decoder model")
    by_rank = model.evaluate_records(records, [codec.rank for codec in codecs.values()])
    return {target: by_rank[codec.rank] for target, codec in codecs.items()}


def _evaluate_bounded_sod_candidate(codec: SodTransitionCodec, records: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Evaluate a bounded SoD candidate and its label-free validation distortion."""

    scores = np.empty(len(records), dtype=np.float64)
    payload = np.empty(len(records), dtype=np.int64)
    code_mse = np.empty(len(records), dtype=np.float64)
    for index, record in enumerate(records):
        scores[index], payload[index], code_mse[index] = codec.evaluate_record_metrics(record)
    return scores, payload, code_mse


def _bounded_sod_payloads(codec: SodTransitionCodec, records: np.ndarray) -> np.ndarray:
    """Measure exact packets without computing score or distortion repeatedly."""

    return np.asarray([len(codec.encode_record(record)) for record in records], dtype=np.int64)


def _assert_payload_capacity(payload: np.ndarray, target: int, context: str) -> None:
    observed = int(np.max(payload)) if len(payload) else 0
    if observed > target:
        raise RuntimeError(f"{context} exceeded its frozen {target}-byte record capacity: observed {observed} bytes")


def _raw_scores(records: np.ndarray, signal_scale: float) -> tuple[np.ndarray, np.ndarray]:
    scores = np.mean(np.sum(records.astype(np.float64) ** 2, axis=2), axis=1) * signal_scale * signal_scale
    payload = np.full(len(records), records.shape[1] * records.shape[2] * 2, dtype=np.int64)
    return scores, payload


def _bootstrap_auc(healthy: np.ndarray, damaged: np.ndarray, seed_offset: int, n_bootstrap: int) -> list[float]:
    rng = np.random.default_rng(SEED + seed_offset)
    healthy = np.asarray(healthy, dtype=np.float64)
    damaged = np.asarray(damaged, dtype=np.float64)
    values = np.empty(n_bootstrap, dtype=np.float64)
    for index in range(n_bootstrap):
        h = healthy[rng.integers(0, len(healthy), len(healthy))]
        d = damaged[rng.integers(0, len(damaged), len(damaged))]
        values[index] = roc_auc_score(np.r_[np.zeros(len(h)), np.ones(len(d))], np.r_[h, d])
    return [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]


def _temperature_matched_stats(
    healthy_temperatures: np.ndarray,
    healthy_scores: np.ndarray,
    damage_temperatures: np.ndarray,
    damage_scores: np.ndarray,
    max_difference: float,
    n_bootstrap: int,
    seed_offset: int,
) -> dict[str, Any]:
    cost = np.abs(healthy_temperatures[:, None] - damage_temperatures[None, :])
    row_index, column_index = linear_sum_assignment(cost)
    keep = cost[row_index, column_index] <= max_difference
    row_index, column_index = row_index[keep], column_index[keep]
    if not len(row_index):
        raise RuntimeError("no temperature-matched test pairs satisfy the frozen maximum difference")
    differences = damage_scores[column_index] - healthy_scores[row_index]
    wins = differences > 0
    ties = differences == 0
    rng = np.random.default_rng(SEED + seed_offset)
    bootstrap = np.empty(n_bootstrap, dtype=np.float64)
    for index in range(n_bootstrap):
        sampled = rng.integers(0, len(wins), len(wins))
        bootstrap[index] = float(np.mean(wins[sampled]))
    return {
        "n_pairs": int(len(wins)),
        "temperature_abs_difference_celsius": {
            "median": float(np.median(cost[row_index, column_index])),
            "p95": float(np.quantile(cost[row_index, column_index], 0.95)),
            "maximum": float(np.max(cost[row_index, column_index])),
        },
        "damage_higher_win_rate": float(np.mean(wins)),
        "tie_rate": float(np.mean(ties)),
        "win_rate_ci95": [float(np.quantile(bootstrap, 0.025)), float(np.quantile(bootstrap, 0.975))],
    }


def _codec_descriptor(codec: RecordCodec) -> dict[str, Any]:
    descriptor = {"name": codec.name, "model_bytes": codec.model_bytes}
    if isinstance(codec, SodTransitionCodec):
        descriptor["delta_codes"] = codec.delta_codes
        descriptor["max_path_payload_bytes"] = codec.max_path_payload_bytes
    elif isinstance(codec, UniformLinearCodec):
        descriptor["stride"] = codec.stride
    elif isinstance(codec, PcaCodec):
        descriptor["rank"] = codec.rank
    elif isinstance(codec, HaarDwtCodec):
        descriptor["top_k"] = codec.top_k
        descriptor["padded_length"] = codec.padded_length
    return descriptor


def _candidate_codecs(
    quantizer: Int16SignalQuantizer,
    pca_model: PcaModel,
    haar_scale: float,
    n_samples: int,
    n_paths: int,
    targets: list[int],
) -> dict[str, dict[int, list[RecordCodec]]]:
    """Build the frozen candidate table separately for each hard capacity."""

    padded_length = next_power_of_two(n_samples)
    sod_deltas = (1, 8, 64, 512, 4096, 8192, 16384, 32767)
    pca_ranks = [rank for rank in (1, 2, 3, 4, 6, 7, 8, 12, 15, 16, 24, 31, 32, 48, 62, 64, 96, 124, 128) if rank <= pca_model.max_rank]
    uniform = [
        UniformLinearCodec(stride=stride, signal_scale=quantizer.scale)
        for stride in (8, 16, 32, 64, 107, 128, 215, 256, 437, 512, 937, 1024, 2048, 2185, 4096, 8192)
    ]
    pca = [PcaCodec(model=pca_model, rank=rank) for rank in pca_ranks]
    haar = [
        HaarDwtCodec(
            top_k=top_k,
            coefficient_scale=haar_scale,
            signal_scale=quantizer.scale,
            padded_length=padded_length,
        )
        for top_k in (1, 2, 3, 4, 6, 7, 8, 12, 15, 16, 24, 30, 31, 32, 48, 61, 62, 64, 96, 124, 128)
    ]

    def path_cap(target: int) -> int:
        for candidate in range(target // n_paths, 0, -1):
            if n_paths * (candidate + len(encode_uvarint(candidate))) <= target:
                return candidate
        raise RuntimeError(f"cannot allocate a decodable SoD path packet within {target} bytes")

    return {
        "sod_transition_bounded": {
            target: [
                SodTransitionCodec(
                    delta_codes=delta,
                    signal_scale=quantizer.scale,
                    max_path_payload_bytes=path_cap(target),
                )
                for delta in sod_deltas
            ]
            for target in targets
        },
        "uniform_linear": {target: list(uniform) for target in targets},
        "pca": {target: list(pca) for target in targets},
        "haar_dwt": {target: list(haar) for target in targets},
    }


def _select_operating_points(
    candidates: dict[str, dict[int, list[RecordCodec]]],
    validation_codes: np.ndarray,
    targets: list[int],
) -> tuple[dict[str, dict[int, RecordCodec]], dict[str, dict[str, list[dict[str, Any]]]]]:
    selected: dict[str, dict[int, RecordCodec]] = {}
    audit: dict[str, dict[str, list[dict[str, Any]]]] = {}
    n_paths, n_samples = validation_codes.shape[1:]
    mse_selection_count = min(8, len(validation_codes))
    mse_selection_indices = np.rint(np.linspace(0, len(validation_codes) - 1, mse_selection_count)).astype(int)
    for codec_name, candidates_by_target in candidates.items():
        audit[codec_name] = {}
        selected[codec_name] = {}
        for target in targets:
            evaluations: list[tuple[int, RecordCodec, dict[str, Any]]] = []
            for candidate_index, codec in enumerate(candidates_by_target[target]):
                maximum = codec.maximum_record_bytes(n_paths, n_samples)
                if maximum is None or maximum > target:
                    continue
                if isinstance(codec, SodTransitionCodec):
                    payload = _bounded_sod_payloads(codec, validation_codes)
                    summary = _summarize_payload(payload)
                else:
                    summary = {
                        "selection_basis": "fixed or conservative worst-case packet bound; no label or test access",
                        "maximum_guaranteed_bytes_per_record": int(maximum),
                    }
                if isinstance(codec, SodTransitionCodec):
                    _assert_payload_capacity(payload, target, f"healthy validation {codec_name}")
                evaluations.append(
                    (
                        candidate_index,
                        codec,
                        {
                            **_codec_descriptor(codec),
                            **summary,
                            "maximum_guaranteed_bytes_per_record": int(maximum),
                        },
                    )
                )
            if not evaluations:
                raise RuntimeError(f"no {codec_name} candidate satisfies the {target}-byte hard capacity")
            if codec_name == "sod_transition_bounded":
                best_payload_distance = min(abs(entry["mean_bytes_per_record"] - target) for _, _, entry in evaluations)
                tied = [item for item in evaluations if abs(item[2]["mean_bytes_per_record"] - target) == best_payload_distance]
                for _, tied_codec, tied_entry in tied:
                    _, _, code_mse = _evaluate_bounded_sod_candidate(tied_codec, validation_codes[mse_selection_indices])
                    tied_entry["healthy_validation_code_mse"] = float(np.mean(code_mse))
                    tied_entry["mse_tie_break_records"] = int(mse_selection_count)
                _, codec, _ = min(
                    tied,
                    key=lambda item: (item[2]["healthy_validation_code_mse"], item[0]),
                )
            else:
                _, codec, _ = min(
                    evaluations,
                    key=lambda item: (target - item[2]["maximum_guaranteed_bytes_per_record"], -item[0]),
                )
            audit[codec_name][str(target)] = [entry for _, _, entry in evaluations]
            selected[codec_name][target] = codec
    return selected, audit


def _condition_result(
    healthy_scores: np.ndarray,
    healthy_payload: np.ndarray,
    healthy_temperatures: np.ndarray,
    damage_scores: np.ndarray,
    damage_payload: np.ndarray,
    damage_temperatures: np.ndarray,
    max_temperature_difference: float,
    n_bootstrap: int,
    seed_offset: int,
) -> dict[str, Any]:
    labels = np.r_[np.zeros(len(healthy_scores)), np.ones(len(damage_scores))]
    scores = np.r_[healthy_scores, damage_scores]
    return {
        "n_healthy_records": int(len(healthy_scores)),
        "n_damage_records": int(len(damage_scores)),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "roc_auc_ci95": _bootstrap_auc(healthy_scores, damage_scores, seed_offset, n_bootstrap),
        "temperature_matched": _temperature_matched_stats(
            healthy_temperatures,
            healthy_scores,
            damage_temperatures,
            damage_scores,
            max_temperature_difference,
            n_bootstrap,
            seed_offset + 1000,
        ),
        "healthy_payload": _summarize_payload(healthy_payload),
        "damage_payload": _summarize_payload(damage_payload),
    }


def _plot_results(results: dict[str, Any], output: Path) -> None:
    cases = ["D04", "D24"]
    labels = {
        "sod_transition_bounded": "Bounded SoD",
        "uniform_linear": "Uniform linear",
        "pca": "PCA",
        "haar_dwt": "Haar DWT",
    }
    fig, axes = plt.subplots(1, len(cases), figsize=(10, 4), sharey=True)
    for axis, case in zip(np.atleast_1d(axes), cases):
        for codec_name, entries in results["test_results"].items():
            ordered = sorted(entries, key=lambda item: item["target_payload_bytes_per_record"])
            x = [item["target_payload_bytes_per_record"] for item in ordered]
            y = [item["conditions"][case]["roc_auc"] for item in ordered]
            axis.semilogx(x, y, marker="o", label=labels.get(codec_name, codec_name))
        axis.set_title(case)
        axis.set_xlabel("hard record capacity (bytes)")
        axis.grid(True, which="both", alpha=0.25)
    axes[0].set_ylabel("held-out record ROC AUC")
    axes[-1].legend(fontsize=8)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def _build_splits(protocol: dict[str, Any], cache_dir: Path, smoke: bool, force_cache: bool) -> tuple[dict[str, CachedSplit], dict[str, Any]]:
    codec_protocol = protocol["codec_benchmark"]
    healthy = OGWSetZip("OGW_CFRP_Temperature_udam.zip")
    d04 = OGWSetZip("OGW_CFRP_Temperature_dam_D04.zip")
    d24 = OGWSetZip("OGW_CFRP_Temperature_dam_D24.zip")
    limit = 4 if smoke else None
    train_indices = _split_indices(healthy, codec_protocol["healthy_train_dates"], limit)
    validation_indices = _split_indices(healthy, codec_protocol["healthy_validation_dates"], limit)
    test_indices = _split_indices(healthy, codec_protocol["healthy_test_dates"], limit)
    if smoke:
        test_temperatures = healthy.temperatures()[test_indices]
        d04_indices = _smoke_temperature_matches(d04, test_temperatures)
        d24_indices = _smoke_temperature_matches(d24, test_temperatures)
    else:
        d04_indices = np.arange(len(d04), dtype=int)
        d24_indices = np.arange(len(d24), dtype=int)
    baseline_count = min(codec_protocol["baseline_pool"]["count"], len(train_indices))
    train_temperatures = healthy.temperatures()[train_indices]
    baseline_local = _temperature_stratified_indices(train_temperatures, baseline_count)
    baseline_source_indices = train_indices[baseline_local]
    baseline_pool = np.stack([_preprocess(healthy.signals(int(index), FREQUENCY_KHZ)) for index in baseline_source_indices])
    alphas = np.asarray(codec_protocol["baseline_pool"]["stretch_factors"], dtype=np.float64)
    splits = {
        "healthy_train": _cache_dataset(cache_dir, "healthy_train", healthy, train_indices, baseline_pool, baseline_source_indices, alphas, force_cache),
        "healthy_validation": _cache_dataset(cache_dir, "healthy_validation", healthy, validation_indices, baseline_pool, baseline_source_indices, alphas, force_cache),
        "healthy_test": _cache_dataset(cache_dir, "healthy_test", healthy, test_indices, baseline_pool, baseline_source_indices, alphas, force_cache),
        "D04": _cache_dataset(cache_dir, "D04_test", d04, d04_indices, baseline_pool, baseline_source_indices, alphas, force_cache),
        "D24": _cache_dataset(cache_dir, "D24_test", d24, d24_indices, baseline_pool, baseline_source_indices, alphas, force_cache),
    }
    manifest = {
        "frequency_khz": FREQUENCY_KHZ,
        "smoke": smoke,
        "baseline_source_indices": baseline_source_indices.tolist(),
        "baseline_temperatures": healthy.temperatures()[baseline_source_indices].tolist(),
        "alphas": alphas.tolist(),
        "splits": {name: {"records": int(len(split.residuals())), "source_dates": split.source_dates} for name, split in splits.items()},
    }
    (cache_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return splits, manifest


def run(args: argparse.Namespace) -> dict[str, Any]:
    protocol = _load_protocol()
    cache_dir = args.cache_dir
    splits, cache_manifest = _build_splits(protocol, cache_dir, args.smoke, args.force_cache)
    train = splits["healthy_train"].residuals()
    validation = splits["healthy_validation"].residuals()
    healthy_test = splits["healthy_test"].residuals()
    d04 = splits["D04"].residuals()
    d24 = splits["D24"].residuals()

    quantizer = Int16SignalQuantizer.fit([train])
    code_splits: dict[str, np.ndarray] = {}
    saturation: dict[str, dict[str, float]] = {}
    for name, residuals in {
        "healthy_train": train,
        "healthy_validation": validation,
        "healthy_test": healthy_test,
        "D04": d04,
        "D24": d24,
    }.items():
        codes, clipped = quantizer.quantize(residuals)
        code_splits[name] = codes
        saturation[name] = {
            "clipped_samples": int(clipped),
            "total_samples": int(codes.size),
            "fraction": float(clipped / max(codes.size, 1)),
        }

    max_rank = 16 if args.smoke else 128
    pca_model = PcaModel.fit(code_splits["healthy_train"], quantizer.scale, max_rank=max_rank)
    haar_scale = fit_haar_scale(code_splits["healthy_train"], quantizer.scale)
    targets = [1024, 2048] if args.smoke else protocol["codec_benchmark"]["target_payload_bytes_per_record"]
    candidates = _candidate_codecs(
        quantizer,
        pca_model,
        haar_scale,
        code_splits["healthy_train"].shape[-1],
        code_splits["healthy_train"].shape[1],
        targets,
    )
    selected, validation_audit = _select_operating_points(candidates, code_splits["healthy_validation"], targets)

    n_bootstrap = 100 if args.smoke else args.bootstrap
    healthy_temperatures = splits["healthy_test"].temperatures()
    results: dict[str, list[dict[str, Any]]] = {}
    pca_evaluations = (
        {
            name: _evaluate_selected_pca_targets(selected["pca"], code_splits[name])
            for name in ("healthy_test", "D04", "D24")
        }
        if "pca" in selected
        else {}
    )
    raw_healthy_score, raw_healthy_payload = _raw_scores(code_splits["healthy_test"], quantizer.scale)
    raw_results = {}
    for offset, (name, split) in enumerate((("D04", splits["D04"]), ("D24", splits["D24"]))):
        damage_score, damage_payload = _raw_scores(code_splits[name], quantizer.scale)
        raw_results[name] = _condition_result(
            raw_healthy_score,
            raw_healthy_payload,
            healthy_temperatures,
            damage_score,
            damage_payload,
            split.temperatures(),
            protocol["codec_benchmark"]["paired_temperature_analysis"]["maximum_difference_celsius"],
            n_bootstrap,
            10_000 + offset,
        )

    for codec_offset, (codec_name, target_map) in enumerate(selected.items()):
        entries = []
        for target_offset, target in enumerate(targets):
            codec = target_map[target]
            if isinstance(codec, PcaCodec):
                healthy_scores, healthy_payload = pca_evaluations["healthy_test"][target]
            else:
                healthy_scores, healthy_payload = _evaluate_codec(codec, code_splits["healthy_test"])
            _assert_payload_capacity(healthy_payload, target, f"healthy test {codec_name}")
            maximum_guaranteed = codec.maximum_record_bytes(
                code_splits["healthy_test"].shape[1], code_splits["healthy_test"].shape[2]
            )
            if maximum_guaranteed is None or maximum_guaranteed > target:
                raise RuntimeError(f"{codec_name} lacks a valid {target}-byte hard-cap proof")
            conditions = {}
            for damage_offset, (damage_name, split) in enumerate((("D04", splits["D04"]), ("D24", splits["D24"]))):
                if isinstance(codec, PcaCodec):
                    damage_scores, damage_payload = pca_evaluations[damage_name][target]
                else:
                    damage_scores, damage_payload = _evaluate_codec(codec, code_splits[damage_name])
                _assert_payload_capacity(damage_payload, target, f"{damage_name} test {codec_name}")
                conditions[damage_name] = _condition_result(
                    healthy_scores,
                    healthy_payload,
                    healthy_temperatures,
                    damage_scores,
                    damage_payload,
                    split.temperatures(),
                    protocol["codec_benchmark"]["paired_temperature_analysis"]["maximum_difference_celsius"],
                    n_bootstrap,
                    20_000 + codec_offset * 100 + target_offset * 10 + damage_offset,
                )
            entries.append(
                {
                    "target_payload_bytes_per_record": int(target),
                    "hard_capacity_guaranteed_bytes_per_record": int(maximum_guaranteed),
                    "selected_from_healthy_validation_only": _codec_descriptor(codec),
                    "conditions": conditions,
                }
            )
            print(
                f"{codec_name} target={target}B: "
                f"D04 AUC={conditions['D04']['roc_auc']:.3f}, D24 AUC={conditions['D24']['roc_auc']:.3f}",
                flush=True,
            )
        results[codec_name] = entries

    output = {
        "protocol_id": protocol["protocol_id"],
        "smoke": bool(args.smoke),
        "system_boundary": protocol["codec_benchmark"]["system_boundary"],
        "selection_boundary": protocol["codec_benchmark"]["operating_point_selection"],
        "payload_capacity_contract": protocol["codec_benchmark"]["payload_accounting"]["hard_capacity_contract"],
        "cache_manifest": cache_manifest,
        "signal_quantizer": {"scale": quantizer.scale, "model_bytes": quantizer.model_bytes, "saturation": saturation},
        "pca_fit": {"max_rank": pca_model.max_rank, "training_records": int(len(train))},
        "haar_fit": {"coefficient_scale": haar_scale},
        "validation_payload_candidate_audit": validation_audit,
        "raw_int16_reference": {"model_bytes": quantizer.model_bytes, "conditions": raw_results},
        "test_results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    _plot_results(output, args.plot)
    print(f"saved {args.output}")
    print(f"saved {args.plot}")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="Use four records per split, rank 16, and two targets.")
    parser.add_argument("--force-cache", action="store_true", help="Recompute residual caches under the frozen protocol.")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plot", type=Path, default=DEFAULT_PLOT)
    parser.add_argument("--bootstrap", type=int, default=1000)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
