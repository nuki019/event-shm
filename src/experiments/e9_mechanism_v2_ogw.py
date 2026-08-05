"""One-shot OGW D12/D16 confirmation under frozen mechanism-v2.

This runner intentionally has no D04/D24 input.  It reuses the historical
healthy residual cache only after validating its frozen E7 representation,
then accesses one MD5-verified D12 or D16 archive, scores every frozen
capacity/delta cell, and writes an auditable result artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.ogw_loader import OGWSetZip
from src.experiments.e7_strict_codec_benchmark import CachedSplit, _cache_dataset, _preprocess, _source_dates
from src.methods.mechanism_v2 import (
    EVENT_FEATURE_NAMES,
    RobustEventDiagnostic,
    RobustScalarNormalizer,
    apply_controlled_injection,
    canonical_collision_probe,
    canonical_terminal_hold_probe,
    control_injection_grid,
    frequency_bands_from_nyquist_fractions,
    grouped_auc_bootstrap,
    paired_group_auc_difference,
    quantization_collision_evidence,
    reconstruct_record_from_trace,
    reconstruction_energy_from_trace,
    record_waveform_metrics,
    score_head_mismatch,
    terminal_hold_evidence,
    trace_record_features,
    trace_summary,
)
from src.methods.strict_codecs import Int16SignalQuantizer, SodRecordTrace, SodTransitionCodec, encode_uvarint


PROTOCOL_PATH = ROOT / "protocols" / "mechanism_v2.json"
MANIFEST_PATH = ROOT / "protocols" / "mechanism_v2_data_manifest.json"
FREEZE_RECEIPT = ROOT / "protocols" / "mechanism_v2_freeze_receipt.json"
STRICT_CACHE_DIR = ROOT / "data" / "interim" / "strict_codec_v1"
DEFAULT_CACHE_DIR = ROOT / "data" / "interim" / "mechanism_v2_ogw"
DEFAULT_CALIBRATION_RECEIPT = ROOT / "results" / "mechanism_v2_ogw_udam_source_receipt.json"
DEFAULT_OUTPUTS = {
    "D12": ROOT / "results" / "mechanism_v2_ogw_d12_confirmation.json",
    "D16": ROOT / "results" / "mechanism_v2_ogw_d16_confirmation.json",
}
SEED = 20260729
FREQUENCY_KHZ = 40
SUPPORTED_PROTOCOL_IDS = {"mechanism-v2", "mechanism-v2.1"}


class ConfirmationError(RuntimeError):
    """Raised when a one-shot confirmation precondition is not satisfied."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfirmationError(f"cannot read {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ConfirmationError(f"{path} must contain a JSON object")
    return payload


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _json_hash(value: Any) -> str:
    return _sha256_bytes(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _git_revision() -> str:
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unavailable"
    tracked = [
        ROOT / "src" / "methods" / "strict_codecs.py",
        ROOT / "src" / "methods" / "mechanism_v2.py",
        ROOT / "src" / "experiments" / "e9_mechanism_v2_ogw.py",
    ]
    digest = hashlib.sha256()
    for path in tracked:
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return f"git:{revision};mechanism_source_sha256:{digest.hexdigest()}"


def _manifest_entry(manifest: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    entries = manifest.get("data_sets")
    if not isinstance(entries, list):
        raise ConfirmationError("frozen manifest lacks data_sets")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("dataset_id") == dataset_id]
    if len(matches) != 1:
        raise ConfirmationError(f"frozen manifest lacks a unique entry for {dataset_id}")
    return matches[0]


def _receipt_files(receipt: dict[str, Any], expected_dataset: str) -> list[dict[str, Any]]:
    if receipt.get("dataset_id") != expected_dataset:
        raise ConfirmationError(f"download receipt does not belong to {expected_dataset}")
    if receipt.get("waveform_access_permitted") is not True:
        raise ConfirmationError(f"download receipt does not permit waveform access for {expected_dataset}")
    files = receipt.get("archive_and_content_hashes")
    if not isinstance(files, list) or not files:
        raise ConfirmationError(f"download receipt has no verified files for {expected_dataset}")
    for item in files:
        if not isinstance(item, dict) or item.get("md5_verified_before_waveform_access") is not True:
            raise ConfirmationError(f"download receipt lacks a pre-access MD5 verification for {expected_dataset}")
    return files


def _receipt_path(file_receipt: dict[str, Any]) -> Path:
    value = file_receipt.get("path")
    if not isinstance(value, str):
        raise ConfirmationError("download receipt file has no path")
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        raise ConfirmationError(f"verified source is no longer present: {path}")
    return path


def _path_cap(target_bytes: int, n_paths: int) -> int:
    for candidate in range(target_bytes // n_paths, 0, -1):
        if n_paths * (candidate + len(encode_uvarint(candidate))) <= target_bytes:
            return candidate
    raise ConfirmationError(f"cannot allocate a decodable path cap within {target_bytes} bytes")


def _quantize_records(records: np.ndarray, quantizer: Int16SignalQuantizer, batch_records: int = 8) -> tuple[np.ndarray, dict[str, float | int]]:
    records = np.asarray(records)
    output = np.empty(records.shape, dtype=np.int16)
    clipped = 0
    for start in range(0, len(records), batch_records):
        stop = min(start + batch_records, len(records))
        codes, batch_clipped = quantizer.quantize(records[start:stop])
        output[start:stop] = codes
        clipped += batch_clipped
    return output, {
        "clipped_samples": int(clipped),
        "total_samples": int(output.size),
        "fraction": float(clipped / max(output.size, 1)),
    }


def _strict_cache_split(cache_dir: Path, name: str, expected_dates: list[str]) -> CachedSplit:
    residual_path = cache_dir / f"{name}_residuals.npy"
    temperature_path = cache_dir / f"{name}_temperatures.npy"
    source_index_path = cache_dir / f"{name}_source_indices.npy"
    complete_path = cache_dir / f"{name}_complete.json"
    if not all(path.is_file() for path in (residual_path, temperature_path, source_index_path, complete_path)):
        raise ConfirmationError(f"strict healthy cache is incomplete for {name}")
    complete = _load_json(complete_path)
    source_indices = np.load(source_index_path)
    expected_shape = (len(source_indices), 66, 13108)
    if tuple(np.load(residual_path, mmap_mode="r").shape) != expected_shape:
        raise ConfirmationError(f"strict healthy cache shape differs for {name}")
    if complete.get("name") != name or complete.get("source_indices") != source_indices.tolist():
        raise ConfirmationError(f"strict healthy cache provenance differs for {name}")
    dates = complete.get("source_dates")
    if not isinstance(dates, list) or not dates or set(dates) - set(expected_dates):
        # Older E7 cache completion files intentionally omit source dates. The
        # top-level cache manifest is checked in _load_healthy_cache instead.
        dates = ["unresolved"] * len(source_indices)
    return CachedSplit(name, residual_path, temperature_path, source_index_path, [str(date) for date in dates])


def _load_healthy_cache(protocol: dict[str, Any], cache_dir: Path) -> tuple[dict[str, CachedSplit], dict[str, Any]]:
    manifest = _load_json(cache_dir / "manifest.json")
    contract = protocol["ogw_representation_contract"]
    if manifest.get("frequency_khz") != FREQUENCY_KHZ or manifest.get("smoke") is not False:
        raise ConfirmationError("strict healthy cache does not match the full 40 kHz representation")
    expected_alphas = contract["baseline_pool"]["stretch_factors"]
    if manifest.get("alphas") != expected_alphas:
        raise ConfirmationError("strict healthy cache baseline stretch factors differ from mechanism-v2")
    split_dates = {
        "healthy_train": contract["healthy_train_dates"],
        "healthy_validation": contract["healthy_validation_dates"],
        "healthy_test": contract["healthy_test_dates"],
    }
    manifest_splits = manifest.get("splits")
    if not isinstance(manifest_splits, dict):
        raise ConfirmationError("strict healthy cache manifest lacks split metadata")
    for name, allowed_dates in split_dates.items():
        reported = manifest_splits.get(name, {}).get("source_dates") if isinstance(manifest_splits.get(name), dict) else None
        if not isinstance(reported, list) or not reported or set(reported) - set(allowed_dates):
            raise ConfirmationError(f"strict healthy cache {name} does not match frozen dates")
    splits = {name: _strict_cache_split(cache_dir, name, dates) for name, dates in split_dates.items()}
    for name in splits:
        splits[name] = CachedSplit(
            name,
            splits[name].residual_path,
            splits[name].temperature_path,
            splits[name].source_index_path,
            [str(value) for value in manifest_splits[name]["source_dates"]],
        )
    return splits, manifest


def _build_damage_cache(
    protocol: dict[str, Any],
    healthy_archive: Path,
    damage_archive: Path,
    condition: str,
    strict_manifest: dict[str, Any],
    cache_dir: Path,
    force_cache: bool,
) -> tuple[CachedSplit, dict[str, Any]]:
    healthy = OGWSetZip(healthy_archive.name, raw_dir=str(healthy_archive.parent))
    damaged = OGWSetZip(damage_archive.name, raw_dir=str(damage_archive.parent))
    baseline_indices = np.asarray(strict_manifest.get("baseline_source_indices"), dtype=int)
    if len(baseline_indices) != protocol["ogw_representation_contract"]["baseline_pool"]["count"]:
        raise ConfirmationError("strict cache baseline index count differs from frozen protocol")
    baseline_pool = np.stack([_preprocess(healthy.signals(int(index), FREQUENCY_KHZ)) for index in baseline_indices])
    alphas = np.asarray(protocol["ogw_representation_contract"]["baseline_pool"]["stretch_factors"], dtype=np.float64)
    source_indices = np.arange(len(damaged), dtype=int)
    split = _cache_dataset(
        cache_dir,
        f"{condition.lower()}_confirmation",
        damaged,
        source_indices,
        baseline_pool,
        baseline_indices,
        alphas,
        force_cache,
    )
    cache_manifest = {
        "schema": "mechanism-v2-ogw-confirmation-cache-v1",
        "condition": condition,
        "frequency_khz": FREQUENCY_KHZ,
        "baseline_source_indices": baseline_indices.tolist(),
        "alphas": alphas.tolist(),
        "damage_source_dates": _source_dates(damaged).tolist(),
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{condition.lower()}_confirmation_manifest.json").write_text(json.dumps(cache_manifest, indent=2) + "\n", encoding="utf-8")
    return split, cache_manifest


@dataclass
class WaveformAccumulator:
    count: int = 0
    scalar_sums: dict[str, float] = field(default_factory=dict)
    band_sums: dict[str, float] = field(default_factory=dict)

    def add(self, metrics: dict[str, Any]) -> None:
        self.count += 1
        for key, value in metrics.items():
            if key == "frequency_band_retention":
                for band, band_value in value.items():
                    self.band_sums[band] = self.band_sums.get(band, 0.0) + float(band_value)
            else:
                self.scalar_sums[key] = self.scalar_sums.get(key, 0.0) + float(value)

    def summary(self) -> dict[str, Any]:
        if not self.count:
            raise ConfirmationError("cannot summarize an empty waveform accumulator")
        return {
            **{key: value / self.count for key, value in sorted(self.scalar_sums.items())},
            "frequency_band_retention": {key: value / self.count for key, value in sorted(self.band_sums.items())},
            "record_count": self.count,
        }

    def extend(self, other: "WaveformAccumulator") -> None:
        self.count += other.count
        for key, value in other.scalar_sums.items():
            self.scalar_sums[key] = self.scalar_sums.get(key, 0.0) + value
        for key, value in other.band_sums.items():
            self.band_sums[key] = self.band_sums.get(key, 0.0) + value


@dataclass
class RecordSetEvaluation:
    features: np.ndarray
    dense_scores: np.ndarray
    reconstruction_scores: np.ndarray
    payload_bytes: np.ndarray
    cap_saturated_path_fraction: np.ndarray
    cap_hold_fraction: np.ndarray
    bounded_waveforms: WaveformAccumulator | None
    quantization_waveforms: WaveformAccumulator | None
    truncation_waveforms: WaveformAccumulator | None
    fixed_trace_receipt: dict[str, Any]

    def event_feature_means(self) -> dict[str, float]:
        means = np.mean(self.features, axis=(0, 1))
        return {name: float(value) for name, value in zip(EVENT_FEATURE_NAMES, means)}


def _trace_hash(values: np.ndarray) -> str:
    return _sha256_bytes(np.asarray(values, dtype="<i8").tobytes())


def _fixed_trace_receipt(trace: SodRecordTrace, n_samples: int) -> dict[str, Any]:
    path = trace.path_traces[0]
    return {
        **trace_summary(path, n_samples),
        "quantized_levels_sha256": _trace_hash(path.quantized_levels),
        "event_times_sha256": _trace_hash(path.transmitted_event_indices),
        "event_level_deltas_sha256": _trace_hash(path.transmitted_event_level_deltas),
    }


def _quantized_reconstruction(trace: SodRecordTrace, delta_codes: int) -> np.ndarray:
    return np.stack(
        [np.clip(path.quantized_levels * delta_codes, -32767, 32767).astype(np.int16) for path in trace.path_traces]
    )


def _evaluate_records(
    records: np.ndarray,
    codec: SodTransitionCodec,
    signal_scale: float,
    sampling_rate_hz: float,
    frequency_bands_hz: list[tuple[float, float]],
    max_lag_samples: int,
    include_waveform_metrics: bool,
) -> RecordSetEvaluation:
    records = np.asarray(records, dtype=np.int16)
    if records.ndim != 3 or not len(records):
        raise ConfirmationError("record set must have shape (records, paths, samples)")
    features = np.empty((len(records), records.shape[1], len(EVENT_FEATURE_NAMES)), dtype=np.float64)
    dense_scores = np.empty(len(records), dtype=np.float64)
    reconstruction_scores = np.empty(len(records), dtype=np.float64)
    payload_bytes = np.empty(len(records), dtype=np.int64)
    saturation = np.empty(len(records), dtype=np.float64)
    holds = np.empty(len(records), dtype=np.float64)
    bounded = WaveformAccumulator() if include_waveform_metrics else None
    quantized = WaveformAccumulator() if include_waveform_metrics else None
    truncation = WaveformAccumulator() if include_waveform_metrics else None
    trace_receipt: dict[str, Any] | None = None
    for index, record in enumerate(records):
        trace, record_features = trace_record_features(codec, record, verify_serialization=index == 0)
        features[index] = record_features
        dense_scores[index] = float(np.mean(np.sum(record.astype(np.float64) ** 2, axis=1)) * signal_scale * signal_scale)
        reconstruction_scores[index] = reconstruction_energy_from_trace(trace, codec.delta_codes, signal_scale, record.shape[1])
        payload_bytes[index] = trace.packet_bytes
        saturation[index] = float(trace.cap_saturated_path_count / len(trace.path_traces))
        holds[index] = float(np.mean([path.cap_hold_samples / record.shape[1] for path in trace.path_traces]))
        if trace_receipt is None:
            trace_receipt = _fixed_trace_receipt(trace, record.shape[1])
        if include_waveform_metrics:
            bounded_reconstruction = reconstruct_record_from_trace(trace, codec.delta_codes, record.shape[1])
            quantized_reconstruction = _quantized_reconstruction(trace, codec.delta_codes)
            bounded.add(record_waveform_metrics(record, bounded_reconstruction, sampling_rate_hz, frequency_bands_hz, max_lag_samples))
            quantized.add(record_waveform_metrics(record, quantized_reconstruction, sampling_rate_hz, frequency_bands_hz, max_lag_samples))
            truncation.add(record_waveform_metrics(quantized_reconstruction, bounded_reconstruction, sampling_rate_hz, frequency_bands_hz, max_lag_samples))
    if trace_receipt is None:
        raise ConfirmationError("record set produced no trace receipt")
    return RecordSetEvaluation(
        features,
        dense_scores,
        reconstruction_scores,
        payload_bytes,
        saturation,
        holds,
        bounded,
        quantized,
        truncation,
        trace_receipt,
    )


def _combine_waveforms(first: WaveformAccumulator, second: WaveformAccumulator) -> dict[str, Any]:
    combined = WaveformAccumulator()
    combined.extend(first)
    combined.extend(second)
    return combined.summary()


def _combine_values(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    return np.concatenate((np.asarray(first), np.asarray(second)))


def _group_ids(prefix: str, source_indices: np.ndarray) -> list[str]:
    return [f"{prefix}:{int(index)}" for index in source_indices]


def _group_split(
    train_indices: np.ndarray,
    validation_indices: np.ndarray,
    healthy_test_indices: np.ndarray,
    damage_indices: np.ndarray,
    condition: str,
) -> dict[str, Any]:
    split = {
        "train": _group_ids("udam", train_indices),
        "validation": _group_ids("udam", validation_indices),
        "test": _group_ids("udam", healthy_test_indices) + _group_ids(condition.lower(), damage_indices),
    }
    return {
        "unit_of_analysis": "monitoring_record",
        "split_manifest_sha256": _json_hash(split),
        "splits": split,
        "paths_or_repeats_are_independent_samples": False,
    }


def _mechanism_probes(capacities: Iterable[int], deltas: Iterable[int], n_paths: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for capacity in capacities:
        cap = _path_cap(int(capacity), n_paths)
        for delta in deltas:
            collision_codec = SodTransitionCodec(delta_codes=int(delta), signal_scale=1.0)
            if int(delta) <= 2:
                output.append(
                    {
                        "capacity_bytes": int(capacity),
                        "delta_codes": int(delta),
                        "proposition": "quantization_collision",
                        "status": "not_applicable",
                        "reason": "no nonzero integer sub-level perturbation exists for this delta_codes value",
                    }
                )
            else:
                baseline, perturbed = canonical_collision_probe(int(delta))
                evidence = quantization_collision_evidence(collision_codec, baseline, perturbed)
                output.append(
                    {
                        "capacity_bytes": int(capacity),
                        "delta_codes": int(delta),
                        "proposition": "quantization_collision",
                        "status": "passed" if evidence["same_quantized_levels"] and evidence["same_serialized_payload"] else "failed",
                        **evidence,
                    }
                )
            bounded = SodTransitionCodec(delta_codes=int(delta), signal_scale=1.0, max_path_payload_bytes=cap)
            first, second = canonical_terminal_hold_probe(int(delta), cap, n_samples=max(64, cap * 2 + 8))
            evidence = terminal_hold_evidence(bounded, first, second)
            output.append(
                {
                    "capacity_bytes": int(capacity),
                    "delta_codes": int(delta),
                    "proposition": "terminal_hold",
                    "status": "passed" if all(
                        evidence[key]
                        for key in ("first_cap_saturated", "second_cap_saturated", "same_serialized_payload", "same_decoded_output")
                    ) else "failed",
                    **evidence,
                }
            )
    return output


def _control_injections(
    train_codes: np.ndarray,
    capacities: list[int],
    deltas: list[int],
    n_paths: int,
    injection_protocol: dict[str, Any],
) -> list[dict[str, Any]]:
    record_count = int(injection_protocol["record_count"])
    path_indices = [int(value) for value in injection_protocol["path_indices"]]
    if record_count > len(train_codes) or any(index < 0 or index >= n_paths for index in path_indices):
        raise ConfirmationError("healthy control record/path selection is invalid")
    record_indices = np.rint(np.linspace(0, len(train_codes) - 1, record_count)).astype(int)
    output: list[dict[str, Any]] = []
    for condition in control_injection_grid(capacities, deltas, injection_protocol):
        delta = int(condition["delta_codes"])
        family = str(condition["family"])
        amplitude = int(np.rint(float(condition["amplitude_delta_multiplier"]) * delta))
        if family == "smooth_subthreshold" and amplitude == 0:
            output.append({**condition, "status": "not_applicable", "reason": "rounded integer-code amplitude is zero"})
            continue
        codec = SodTransitionCodec(
            delta_codes=delta,
            signal_scale=1.0,
            max_path_payload_bytes=_path_cap(int(condition["capacity_bytes"]), n_paths),
        )
        payload_equal = []
        event_count_difference = []
        hold_difference = []
        input_relative_change = []
        decoded_relative_change = []
        for record_index in record_indices:
            for path_index in path_indices:
                source = train_codes[record_index, path_index]
                width = max(1, int(round(float(condition["width_fraction_of_record"]) * len(source))))
                injected = apply_controlled_injection(
                    source,
                    family=family,
                    amplitude_codes=amplitude,
                    position_fraction=float(condition["position_fraction"]),
                    width_samples=width,
                    phase_shift_samples=int(condition["phase_shift_samples"]),
                )
                source_trace = codec.trace_path(source)
                injected_trace = codec.trace_path(injected)
                source_decoded = reconstruct_record_from_trace(
                    SodRecordTrace(source_trace.payload, (source_trace,)), delta, len(source)
                )[0]
                injected_decoded = reconstruct_record_from_trace(
                    SodRecordTrace(injected_trace.payload, (injected_trace,)), delta, len(source)
                )[0]
                payload_equal.append(float(source_trace.payload == injected_trace.payload))
                event_count_difference.append(float(injected_trace.event_count - source_trace.event_count))
                hold_difference.append(float((injected_trace.cap_hold_samples - source_trace.cap_hold_samples) / len(source)))
                input_relative_change.append(float(np.linalg.norm(injected.astype(np.float64) - source) / max(np.linalg.norm(source), 1e-12)))
                decoded_relative_change.append(
                    float(np.linalg.norm(injected_decoded.astype(np.float64) - source_decoded) / max(np.linalg.norm(source_decoded), 1e-12))
                )
        output.append(
            {
                **condition,
                "status": "evaluated",
                "healthy_record_indices": record_indices.tolist(),
                "path_indices": path_indices,
                "mean_payload_identical_fraction": float(np.mean(payload_equal)),
                "mean_event_count_difference": float(np.mean(event_count_difference)),
                "mean_cap_hold_fraction_difference": float(np.mean(hold_difference)),
                "mean_input_relative_change": float(np.mean(input_relative_change)),
                "mean_decoded_relative_change": float(np.mean(decoded_relative_change)),
            }
        )
    return output


def _schema_gate() -> dict[str, Any]:
    inventory = {
        "schema": "OGW_CFRP_Temperature_zip_h5_v1",
        "waveform_dataset_path": "/pitchcatch/catch",
        "waveform_shape": [66, 13108],
        "sampling_rate_path": "/command/pitchcatch/sampling_frequency",
        "temperature_path": "/Temperature/values",
        "record_identifier": "archive folder index",
    }
    return {"status": "passed", "schema_fingerprint_sha256": _json_hash(inventory), "inventory": inventory}


def run(args: argparse.Namespace) -> dict[str, Any]:
    protocol = _load_json(args.protocol)
    manifest = _load_json(args.manifest)
    freeze = _load_json(args.freeze_receipt)
    if protocol.get("protocol_id") not in SUPPORTED_PROTOCOL_IDS or protocol.get("status") != "frozen_before_new_waveform_access":
        raise ConfirmationError("supported mechanism-v2 protocol is not frozen")
    if freeze.get("protocol_sha256") != _sha256_file(args.protocol) or freeze.get("data_manifest_sha256") != _sha256_file(args.manifest):
        raise ConfirmationError("pre-access freeze receipt differs from the current protocol or manifest")
    condition = args.condition.upper()
    dataset_id = f"ogw_cfrp_temperature_dam_{condition.lower()}"
    data_entry = _manifest_entry(manifest, dataset_id)
    if data_entry.get("role") != "same_plate_blind_confirmation":
        raise ConfirmationError(f"{dataset_id} is not a frozen blind confirmation source")
    confirmation_receipt = _load_json(args.confirmation_receipt)
    confirmation_files = _receipt_files(confirmation_receipt, dataset_id)
    if len(confirmation_files) != 1:
        raise ConfirmationError("OGW confirmation receipt must contain exactly one archive")
    damage_archive = _receipt_path(confirmation_files[0])
    calibration_receipt = _load_json(args.calibration_receipt)
    calibration_files = _receipt_files(calibration_receipt, "ogw_cfrp_temperature_udam")
    healthy_archive_matches = [item for item in calibration_files if item.get("filename") == "OGW_CFRP_Temperature_udam.zip"]
    if len(healthy_archive_matches) != 1:
        raise ConfirmationError("healthy calibration receipt lacks the OGW undamaged archive")
    healthy_archive = _receipt_path(healthy_archive_matches[0])
    healthy_splits, strict_manifest = _load_healthy_cache(protocol, args.strict_cache_dir)
    damage_split, damage_cache_manifest = _build_damage_cache(
        protocol,
        healthy_archive,
        damage_archive,
        condition,
        strict_manifest,
        args.cache_dir,
        args.force_cache,
    )
    train_residuals = healthy_splits["healthy_train"].residuals()
    healthy_residuals = healthy_splits["healthy_test"].residuals()
    damage_residuals = damage_split.residuals()
    quantizer = Int16SignalQuantizer.fit([train_residuals])
    train_codes, train_saturation = _quantize_records(train_residuals, quantizer)
    healthy_codes, healthy_saturation = _quantize_records(healthy_residuals, quantizer)
    damage_codes, damage_saturation = _quantize_records(damage_residuals, quantizer)
    capacities = [int(value) for value in protocol["ogw_representation_contract"]["payload_accounting"]["capacity_bytes_per_record"]]
    deltas = [int(value) for value in protocol["eventization_grid"]["delta_codes"]]
    bands = frequency_bands_from_nyquist_fractions(
        float(protocol["ogw_representation_contract"]["sampling_rate_hz"]),
        protocol["eventization_grid"]["waveform_metrics"]["frequency_bands_as_nyquist_fractions"],
    )
    max_lag = max(1, int(round(train_codes.shape[-1] * float(protocol["eventization_grid"]["waveform_metrics"]["peak_cross_correlation_max_lag_fraction_of_record"]))))
    healthy_source_indices = np.load(healthy_splits["healthy_test"].source_index_path)
    train_source_indices = np.load(healthy_splits["healthy_train"].source_index_path)
    validation_source_indices = np.load(healthy_splits["healthy_validation"].source_index_path)
    damage_source_indices = np.load(damage_split.source_index_path)
    group_split = _group_split(train_source_indices, validation_source_indices, healthy_source_indices, damage_source_indices, condition)
    test_groups = group_split["splits"]["test"]
    labels: np.ndarray | None = None
    grid_results: list[dict[str, Any]] = []
    for capacity in capacities:
        path_cap = _path_cap(capacity, train_codes.shape[1])
        for delta in deltas:
            codec = SodTransitionCodec(delta_codes=delta, signal_scale=quantizer.scale, max_path_payload_bytes=path_cap)
            train = _evaluate_records(train_codes, codec, quantizer.scale, float(protocol["ogw_representation_contract"]["sampling_rate_hz"]), bands, max_lag, False)
            healthy = _evaluate_records(healthy_codes, codec, quantizer.scale, float(protocol["ogw_representation_contract"]["sampling_rate_hz"]), bands, max_lag, True)
            damage = _evaluate_records(damage_codes, codec, quantizer.scale, float(protocol["ogw_representation_contract"]["sampling_rate_hz"]), bands, max_lag, True)
            diagnostic = RobustEventDiagnostic.fit(train.features)
            dense_normalizer = RobustScalarNormalizer.fit(train.dense_scores)
            reconstruction_normalizer = RobustScalarNormalizer.fit(train.reconstruction_scores)
            event_scores = {
                head: _combine_values(diagnostic.score(healthy.features)[head], diagnostic.score(damage.features)[head])
                for head in protocol["eventization_grid"]["diagnostic"]["heads"]
            }
            dense_scores = _combine_values(healthy.dense_scores, damage.dense_scores)
            reconstruction_scores = _combine_values(healthy.reconstruction_scores, damage.reconstruction_scores)
            # Labels are deliberately constructed only after all feature and
            # waveform score arrays above have been materialized.
            if labels is None:
                labels = np.concatenate((np.zeros(len(healthy_codes), dtype=int), np.ones(len(damage_codes), dtype=int)))
            event_auc = {
                head: grouped_auc_bootstrap(labels, scores, test_groups, int(protocol["statistics"]["group_bootstrap"]["replicates"]), SEED + capacity + delta + offset)
                for offset, (head, scores) in enumerate(event_scores.items())
            }
            paired = {
                head: paired_group_auc_difference(
                    labels,
                    scores,
                    dense_scores,
                    test_groups,
                    int(protocol["statistics"]["group_bootstrap"]["replicates"]),
                    SEED + capacity + delta + 100 + offset,
                )
                for offset, (head, scores) in enumerate(event_scores.items())
            }
            bounded_metrics = _combine_waveforms(healthy.bounded_waveforms, damage.bounded_waveforms)
            bounded_metrics["event_density"] = float(np.mean(_combine_values(healthy.features[..., 0], damage.features[..., 0])))
            bounded_metrics["cap_hold_fraction"] = float(np.mean(_combine_values(healthy.cap_hold_fraction, damage.cap_hold_fraction)))
            payload = _combine_values(healthy.payload_bytes, damage.payload_bytes)
            saturation = _combine_values(healthy.cap_saturated_path_fraction, damage.cap_saturated_path_fraction)
            holds = _combine_values(healthy.cap_hold_fraction, damage.cap_hold_fraction)
            grid_results.append(
                {
                    "capacity_bytes": capacity,
                    "delta_codes": delta,
                    "waveform_metrics": bounded_metrics,
                    "event_statistics": {
                        "mean_event_features": {
                            name: float(value)
                            for name, value in zip(EVENT_FEATURE_NAMES, np.mean(_combine_values(healthy.features, damage.features), axis=(0, 1)))
                        },
                        "fixed_trace_receipt": {
                            "healthy": healthy.fixed_trace_receipt,
                            "damage": damage.fixed_trace_receipt,
                            "event_times_sha256": healthy.fixed_trace_receipt["event_times_sha256"],
                            "event_level_deltas_sha256": healthy.fixed_trace_receipt["event_level_deltas_sha256"],
                        },
                    },
                    "event_diagnostic": event_auc,
                    "paired_group_auc_difference_vs_dense_energy": paired,
                    "loss_decomposition": {
                        "quantization_only": _combine_waveforms(healthy.quantization_waveforms, damage.quantization_waveforms),
                        "hard_cap_truncation": _combine_waveforms(healthy.truncation_waveforms, damage.truncation_waveforms),
                        "score_head_mismatch": {
                            head: score_head_mismatch(
                                dense_scores,
                                reconstruction_scores,
                                scores,
                                dense_normalizer,
                                reconstruction_normalizer,
                            )
                            for head, scores in event_scores.items()
                        },
                    },
                    "cap_evidence": {
                        "path_cap_bytes": path_cap,
                        "hard_capacity_guaranteed_bytes_per_record": codec.maximum_record_bytes(train_codes.shape[1], train_codes.shape[2]),
                        "all_packets_within_declared_capacity": bool(np.max(payload) <= capacity),
                        "mean_bytes_per_record": float(np.mean(payload)),
                        "maximum_bytes_per_record": int(np.max(payload)),
                        "bits_per_original_sample": float(np.mean(payload) * 8.0 / (train_codes.shape[1] * train_codes.shape[2])),
                        "cap_saturated_path_fraction": float(np.mean(saturation)),
                        "mean_cap_hold_fraction": float(np.mean(holds)),
                    },
                    "condition_metrics": {
                        "healthy_test": healthy.bounded_waveforms.summary(),
                        "damage_confirmation": damage.bounded_waveforms.summary(),
                    },
                }
            )
            print(f"{condition} capacity={capacity} delta={delta}: global AUC={event_auc['global']['roc_auc']:.3f}, max-path AUC={event_auc['max_path']['roc_auc']:.3f}", flush=True)
    result = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": _sha256_file(args.protocol),
        "data_manifest_sha256": _sha256_file(args.manifest),
        "code_revision": _git_revision(),
        "outcome_type": "confirmation",
        "data": {
            "dataset_id": dataset_id,
            "data_role": data_entry["role"],
            "archive_and_content_hashes": calibration_files + confirmation_files,
            "schema_gate": _schema_gate(),
            "cache_manifest": damage_cache_manifest,
            "healthy_cache_manifest_sha256": _sha256_file(args.strict_cache_dir / "manifest.json"),
        },
        "selection_receipt": {
            "discovery_data_used_for_selection": False,
            "posthoc_configuration_selection": False,
            "all_configurations_fixed_before_confirmation": True,
            "test_labels_read_after_scoring": True,
            "waveform_scoring_started": True,
            "description": "D04/D24 are not opened by this runner. Quantizer and both robust normalizers use healthy training records only; labels are constructed after complete score arrays exist.",
        },
        "configuration": {
            "capacity_bytes_per_record": capacities,
            "delta_codes": deltas,
            "event_features": list(EVENT_FEATURE_NAMES),
            "aggregation_heads": protocol["eventization_grid"]["diagnostic"]["heads"],
            "control_injection_grid_sha256": _json_hash(control_injection_grid(capacities, deltas, protocol["healthy_control_injections"])),
        },
        "group_split": group_split,
        "signal_quantizer": {
            "scale": quantizer.scale,
            "model_bytes": quantizer.model_bytes,
            "saturation": {"healthy_train": train_saturation, "healthy_test": healthy_saturation, "damage_confirmation": damage_saturation},
        },
        "grid_results": grid_results,
        "mechanism_probes": _mechanism_probes(capacities, deltas, train_codes.shape[1]),
        "control_injections": _control_injections(train_codes, capacities, deltas, train_codes.shape[1], protocol["healthy_control_injections"]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise ConfirmationError(f"refusing to overwrite a one-shot confirmation result: {args.output}")
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"saved {args.output}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", choices=("D12", "D16"), required=True)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--freeze-receipt", type=Path, default=FREEZE_RECEIPT)
    parser.add_argument("--calibration-receipt", type=Path, default=DEFAULT_CALIBRATION_RECEIPT)
    parser.add_argument("--confirmation-receipt", type=Path, required=True)
    parser.add_argument("--strict-cache-dir", type=Path, default=STRICT_CACHE_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--force-cache", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is None:
        args.output = DEFAULT_OUTPUTS[args.condition]
    return args


if __name__ == "__main__":
    try:
        run(parse_args())
    except ConfirmationError as error:
        print(f"MECHANISM-V2 OGW CONFIRMATION FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
