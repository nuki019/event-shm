"""D16 one-shot blind confirmation for mechanism-v2.6.

Uses the frozen E7 calibration (quantizer, baseline pool, stretch factors)
without refitting.  D16 replaces the retired D12 as the same-plate blind
confirmation source.  All codec operating points are re-selected on the
healthy validation split under the frozen protocol; test labels are used
only for final metrics.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
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

PROTOCOL_PATH = ROOT / "protocols" / "mechanism_v2_6.json"
E7_CACHE_DIR = ROOT / "data" / "interim" / "strict_codec_v1"
D16_CACHE_DIR = ROOT / "data" / "interim" / "mechanism_v2_6_d16"
DEFAULT_OUTPUT = ROOT / "results" / "mechanism_v2_6_ogw_d16_confirmation.json"
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


def _source_dates(dataset: OGWSetZip) -> np.ndarray:
    return np.asarray([folder[:8] for folder in dataset.folder_list])


def _temperature_stratified_indices(temperatures: np.ndarray, count: int) -> np.ndarray:
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
    residual_path = cache_dir / f"{name}_residuals.npy"
    temperature_path = cache_dir / f"{name}_temperatures.npy"
    source_index_path = cache_dir / f"{name}_source_indices.npy"
    complete_path = cache_dir / f"{name}_complete.json"
    dates = _source_dates(dataset)[source_indices].tolist()
    expected_shape = (len(source_indices), 66, 13108)
    if not force and all(p.exists() for p in (residual_path, temperature_path, source_index_path, complete_path)):
        existing = np.load(residual_path, mmap_mode="r")
        existing_indices = np.load(source_index_path)
        try:
            completion = json.loads(complete_path.read_text(encoding="utf-8"))
            newest_data_mtime = max(p.stat().st_mtime for p in (residual_path, temperature_path, source_index_path))
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


def _split_indices(dataset: OGWSetZip, allowed_dates: list[str]) -> np.ndarray:
    dates = _source_dates(dataset)
    selected = np.flatnonzero(np.isin(dates, allowed_dates))
    if not len(selected):
        raise RuntimeError(f"no records selected for dates {allowed_dates}")
    return selected


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


def _assert_payload_capacity(payload: np.ndarray, target: int, context: str) -> None:
    observed = int(np.max(payload)) if len(payload) else 0
    if observed > target:
        raise RuntimeError(f"{context} exceeded its frozen {target}-byte record capacity: observed {observed} bytes")


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


def _condition_result(
    healthy_scores: np.ndarray,
    healthy_payload: np.ndarray,
    healthy_temperatures: np.ndarray,
    damage_scores: np.ndarray,
    damage_payload: np.ndarray,
    damage_temperatures: np.ndarray,
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
        "healthy_payload": _summarize_payload(healthy_payload),
        "damage_payload": _summarize_payload(damage_payload),
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


def _select_operating_points(
    candidates: dict[str, dict[int, list[RecordCodec]]],
    validation_codes: np.ndarray,
    targets: list[int],
) -> dict[str, dict[int, RecordCodec]]:
    selected: dict[str, dict[int, RecordCodec]] = {}
    n_paths, n_samples = validation_codes.shape[1:]
    for codec_name, candidates_by_target in candidates.items():
        selected[codec_name] = {}
        for target in targets:
            evaluations = []
            for candidate_index, codec in enumerate(candidates_by_target[target]):
                maximum = codec.maximum_record_bytes(n_paths, n_samples)
                if maximum is None or maximum > target:
                    continue
                evaluations.append((candidate_index, codec, maximum))
            if not evaluations:
                raise RuntimeError(f"no {codec_name} candidate satisfies the {target}-byte hard capacity")
            if codec_name == "sod_transition_bounded":
                # Compute actual payloads on validation
                payloads = []
                for _, codec, _ in evaluations:
                    p = np.asarray([len(codec.encode_record(record)) for record in validation_codes], dtype=np.int64)
                    payloads.append(float(np.mean(p)))
                best_idx = int(np.argmin([abs(p - target) for p in payloads]))
                selected[codec_name][target] = evaluations[best_idx][1]
            else:
                _, codec, _ = min(evaluations, key=lambda item: (target - item[2], -item[0]))
                selected[codec_name][target] = codec
    return selected


def run(args: argparse.Namespace) -> dict[str, Any]:
    protocol = _load_protocol()
    ogw = protocol["ogw_representation_contract"]

    # Reuse E7 healthy cache; rebuild only D16
    healthy = OGWSetZip("OGW_CFRP_Temperature_udam.zip")
    d16 = OGWSetZip("OGW_CFRP_Temperature_dam_D16.zip")

    train_indices = _split_indices(healthy, ogw["healthy_train_dates"])
    validation_indices = _split_indices(healthy, ogw["healthy_validation_dates"])
    test_indices = _split_indices(healthy, ogw["healthy_test_dates"])
    d16_indices = np.arange(len(d16), dtype=int)

    baseline_count = min(ogw["baseline_pool"]["count"], len(train_indices))
    train_temperatures = healthy.temperatures()[train_indices]
    baseline_local = _temperature_stratified_indices(train_temperatures, baseline_count)
    baseline_source_indices = train_indices[baseline_local]
    baseline_pool = np.stack([_preprocess(healthy.signals(int(index), FREQUENCY_KHZ)) for index in baseline_source_indices])
    alphas = np.asarray(ogw["baseline_pool"]["stretch_factors"], dtype=np.float64)

    # Load or cache healthy splits from E7 cache
    train = _cache_dataset(E7_CACHE_DIR, "healthy_train", healthy, train_indices, baseline_pool, baseline_source_indices, alphas, args.force_cache)
    validation = _cache_dataset(E7_CACHE_DIR, "healthy_validation", healthy, validation_indices, baseline_pool, baseline_source_indices, alphas, args.force_cache)
    healthy_test = _cache_dataset(E7_CACHE_DIR, "healthy_test", healthy, test_indices, baseline_pool, baseline_source_indices, alphas, args.force_cache)
    d16_split = _cache_dataset(D16_CACHE_DIR, "D16_test", d16, d16_indices, baseline_pool, baseline_source_indices, alphas, args.force_cache)

    train_residuals = train.residuals()
    validation_residuals = validation.residuals()
    healthy_test_residuals = healthy_test.residuals()
    d16_residuals = d16_split.residuals()

    quantizer = Int16SignalQuantizer.fit([train_residuals])
    code_splits = {}
    saturation = {}
    for name, residuals in {
        "healthy_train": train_residuals,
        "healthy_validation": validation_residuals,
        "healthy_test": healthy_test_residuals,
        "D16": d16_residuals,
    }.items():
        codes, clipped = quantizer.quantize(residuals)
        code_splits[name] = codes
        saturation[name] = {
            "clipped_samples": int(clipped),
            "total_samples": int(codes.size),
            "fraction": float(clipped / max(codes.size, 1)),
        }

    max_rank = 128
    pca_model = PcaModel.fit(code_splits["healthy_train"], quantizer.scale, max_rank=max_rank)
    haar_scale = fit_haar_scale(code_splits["healthy_train"], quantizer.scale)
    targets = ogw["payload_accounting"]["capacity_bytes_per_record"]
    n_samples = code_splits["healthy_train"].shape[-1]
    n_paths = code_splits["healthy_train"].shape[1]
    padded_length = next_power_of_two(n_samples)

    # Build candidate codecs (same as E7)
    sod_deltas = (1, 8, 64, 512, 4096, 8192, 16384, 32767)
    pca_ranks = [r for r in (1, 2, 3, 4, 6, 7, 8, 12, 15, 16, 24, 31, 32, 48, 62, 64, 96, 124, 128) if r <= pca_model.max_rank]
    uniform_candidates = [UniformLinearCodec(stride=s, signal_scale=quantizer.scale) for s in (8, 16, 32, 64, 107, 128, 215, 256, 437, 512, 937, 1024, 2048, 2185, 4096, 8192)]
    pca_candidates = [PcaCodec(model=pca_model, rank=r) for r in pca_ranks]
    haar_candidates = [HaarDwtCodec(top_k=k, coefficient_scale=haar_scale, signal_scale=quantizer.scale, padded_length=padded_length) for k in (1, 2, 3, 4, 6, 7, 8, 12, 15, 16, 24, 30, 31, 32, 48, 61, 62, 64, 96, 124, 128)]

    def _pc(candidate: int) -> int:
        for c in range(candidate, 0, -1):
            if n_paths * (c + len(encode_uvarint(c))) <= candidate:
                return c
        raise RuntimeError(f"cannot allocate path cap within {candidate}")

    candidates = {
        "sod_transition_bounded": {
            target: [SodTransitionCodec(delta_codes=d, signal_scale=quantizer.scale, max_path_payload_bytes=_pc(target)) for d in sod_deltas]
            for target in targets
        },
        "uniform_linear": {target: list(uniform_candidates) for target in targets},
        "pca": {target: list(pca_candidates) for target in targets},
        "haar_dwt": {target: list(haar_candidates) for target in targets},
    }

    selected = _select_operating_points(candidates, code_splits["healthy_validation"], targets)

    n_bootstrap = 1000
    healthy_temperatures = healthy_test.temperatures()
    results: dict[str, list[dict[str, Any]]] = {}

    # Pre-evaluate PCA for all targets
    pca_targets = {target: codec for target, codec in selected.get("pca", {}).items()}
    pca_healthy = {}
    pca_d16 = {}
    if pca_targets:
        pca_model_eval = next(iter(pca_targets.values())).model
        ranks = [codec.rank for codec in pca_targets.values()]
        by_rank = pca_model_eval.evaluate_records(code_splits["healthy_test"], ranks)
        for target, codec in pca_targets.items():
            pca_healthy[target] = by_rank[codec.rank]
        by_rank_d16 = pca_model_eval.evaluate_records(code_splits["D16"], ranks)
        for target, codec in pca_targets.items():
            pca_d16[target] = by_rank_d16[codec.rank]

    for codec_offset, (codec_name, target_map) in enumerate(selected.items()):
        entries = []
        for target_offset, target in enumerate(targets):
            codec = target_map[target]
            if isinstance(codec, PcaCodec):
                healthy_scores, healthy_payload = pca_healthy[target]
            else:
                healthy_scores, healthy_payload = _evaluate_codec(codec, code_splits["healthy_test"])
            _assert_payload_capacity(healthy_payload, target, f"healthy test {codec_name}")

            if isinstance(codec, PcaCodec):
                damage_scores, damage_payload = pca_d16[target]
            else:
                damage_scores, damage_payload = _evaluate_codec(codec, code_splits["D16"])
            _assert_payload_capacity(damage_payload, target, f"D16 test {codec_name}")

            conditions = {
                "D16": _condition_result(
                    healthy_scores, healthy_payload, healthy_temperatures,
                    damage_scores, damage_payload, d16_split.temperatures(),
                    n_bootstrap, 20_000 + codec_offset * 100 + target_offset,
                )
            }
            entries.append({
                "target_payload_bytes_per_record": int(target),
                "hard_capacity_guaranteed_bytes_per_record": int(codec.maximum_record_bytes(n_paths, n_samples) or 0),
                "selected_from_healthy_validation_only": _codec_descriptor(codec),
                "conditions": conditions,
            })
            print(
                f"{codec_name} target={target}B: D16 AUC={conditions['D16']['roc_auc']:.3f}",
                flush=True,
            )
        results[codec_name] = entries

    output = {
        "protocol_id": protocol["protocol_id"],
        "data_role": "same_plate_blind_confirmation",
        "system_boundary": ogw["payload_accounting"],
        "calibration_binding": {
            "healthy_train_dates": ogw["healthy_train_dates"],
            "baseline_source_indices": baseline_source_indices.tolist(),
            "baseline_count": int(baseline_count),
        },
        "signal_quantizer": {"scale": quantizer.scale, "model_bytes": quantizer.model_bytes, "saturation": saturation},
        "pca_fit": {"max_rank": pca_model.max_rank, "training_records": int(len(train_residuals))},
        "haar_fit": {"coefficient_scale": haar_scale},
        "test_results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"saved {args.output}")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-cache", action="store_true", help="Recompute residual caches.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
