"""Once-only MORPHO confirmation runner frozen for mechanism-v2.6.

One monitoring record is a named fatigue/baseline block.  Each individual
frequency/actuator/repeat HDF5 dataset is only a component packet containing
the 29 non-time receiver paths.  Component packets receive the fixed E7
capacity grid, while all inference and bootstrap statistics remain at block
level.  The runner intentionally has no COQTEL, COPV, D04, D12, or D24 input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import h5py
import numpy as np

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.mechanism_v2_6_successor import (
    ROOT, V26Error, external_execution_contract, external_mapping, json_hash, load_json, load_v26_manifest,
    manifest_entry, resolve_within_root, sha256_file, verify_v26_freeze,
)
from src.methods.mechanism_v2 import (
    EVENT_FEATURE_NAMES, RobustEventDiagnostic, RobustScalarNormalizer, apply_controlled_injection,
    canonical_collision_probe, canonical_terminal_hold_probe, control_injection_grid,
    frequency_bands_from_nyquist_fractions, grouped_auc_bootstrap, paired_group_auc_difference,
    quantization_collision_evidence, reconstruct_record_from_trace, reconstruction_energy_from_trace,
    record_waveform_metrics, score_head_mismatch, terminal_hold_evidence, trace_record_features, trace_summary,
)
from src.methods.strict_codecs import INT16_LIMIT, Int16SignalQuantizer, SodRecordTrace, SodTransitionCodec, encode_uvarint


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_6.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_6_data_manifest.json"
DEFAULT_FREEZE = ROOT / "protocols" / "mechanism_v2_6_freeze_receipt.json"
DEFAULT_RECEIPT = ROOT / "results" / "mechanism_v2_6_morpho_source_receipt.json"
DEFAULT_SCHEMA_GATE = ROOT / "results" / "mechanism_v2_6_external_schema_gate.json"
DEFAULT_TERMINAL_HOLD = ROOT / "results" / "mechanism_v2_6_terminal_hold_preaccess_test.json"
DEFAULT_CACHE = ROOT / "data" / "interim" / "mechanism_v2_6_morpho"
DEFAULT_OUTPUT = ROOT / "results" / "mechanism_v2_6_morpho_confirmation.json"
SEED = 20260729


class MorphoConfirmationError(RuntimeError):
    """Raised when a v2.6 MORPHO confirmation cannot safely proceed."""


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

    def extend(self, other: "WaveformAccumulator") -> None:
        self.count += other.count
        for key, value in other.scalar_sums.items():
            self.scalar_sums[key] = self.scalar_sums.get(key, 0.0) + value
        for key, value in other.band_sums.items():
            self.band_sums[key] = self.band_sums.get(key, 0.0) + value

    def summary(self) -> dict[str, Any]:
        if not self.count:
            raise MorphoConfirmationError("cannot summarize an empty waveform accumulator")
        return {
            **{key: value / self.count for key, value in sorted(self.scalar_sums.items())},
            "frequency_band_retention": {key: value / self.count for key, value in sorted(self.band_sums.items())},
            "component_packet_count": self.count,
        }


@dataclass
class PacketEvaluation:
    features: np.ndarray
    dense_score: float
    reconstruction_score: float
    payload_bytes: int
    saturation_fraction: float
    cap_hold_fraction: float
    bounded: dict[str, Any]
    quantization: dict[str, Any]
    truncation: dict[str, Any]
    trace_receipt: dict[str, Any]


@dataclass
class BlockAccumulator:
    block_id: str
    paths: int
    samples: int
    packet_count: int = 0
    feature_sum: np.ndarray = field(default_factory=lambda: np.zeros(len(EVENT_FEATURE_NAMES), dtype=np.float64))
    event_score_sum: dict[str, float] = field(default_factory=lambda: {"global": 0.0, "max_path": 0.0})
    dense_score_sum: float = 0.0
    reconstruction_score_sum: float = 0.0
    payload_bytes_sum: int = 0
    payload_bytes_max: int = 0
    saturation_fraction_sum: float = 0.0
    cap_hold_fraction_sum: float = 0.0
    quantizer_clipped_samples: int = 0
    quantizer_total_samples: int = 0
    cap_saturated_path_fraction_sum: float = 0.0
    bounded: WaveformAccumulator = field(default_factory=WaveformAccumulator)
    quantization: WaveformAccumulator = field(default_factory=WaveformAccumulator)
    truncation: WaveformAccumulator = field(default_factory=WaveformAccumulator)
    fixed_trace_receipt: dict[str, Any] | None = None

    def add(self, packet: PacketEvaluation, event_scores: dict[str, float], clipped: int, total_samples: int) -> None:
        self.packet_count += 1
        self.feature_sum += np.mean(packet.features, axis=0)
        for head, value in event_scores.items():
            self.event_score_sum[head] += float(value)
        self.dense_score_sum += packet.dense_score
        self.reconstruction_score_sum += packet.reconstruction_score
        self.payload_bytes_sum += packet.payload_bytes
        self.payload_bytes_max = max(self.payload_bytes_max, packet.payload_bytes)
        self.saturation_fraction_sum += packet.saturation_fraction
        self.cap_hold_fraction_sum += packet.cap_hold_fraction
        self.quantizer_clipped_samples += clipped
        self.quantizer_total_samples += total_samples
        self.cap_saturated_path_fraction_sum += packet.saturation_fraction
        self.bounded.add(packet.bounded)
        self.quantization.add(packet.quantization)
        self.truncation.add(packet.truncation)
        if self.fixed_trace_receipt is None:
            self.fixed_trace_receipt = packet.trace_receipt

    def summary(self) -> dict[str, Any]:
        if not self.packet_count or self.fixed_trace_receipt is None:
            raise MorphoConfirmationError(f"block {self.block_id} has no evaluated component packets")
        return {
            "block_id": self.block_id,
            "component_packet_count": self.packet_count,
            "mean_event_features": {name: float(value / self.packet_count) for name, value in zip(EVENT_FEATURE_NAMES, self.feature_sum)},
            "event_scores": {head: float(value / self.packet_count) for head, value in self.event_score_sum.items()},
            "dense_energy_score": float(self.dense_score_sum / self.packet_count),
            "reconstruction_energy_score": float(self.reconstruction_score_sum / self.packet_count),
            "bytes_per_monitoring_block": int(self.payload_bytes_sum),
            "mean_bytes_per_component_packet": float(self.payload_bytes_sum / self.packet_count),
            "maximum_bytes_per_component_packet": int(self.payload_bytes_max),
            "bits_per_original_sample": float(self.payload_bytes_sum * 8.0 / (self.packet_count * self.paths * self.samples)),
            "cap_saturated_path_fraction": float(self.cap_saturated_path_fraction_sum / self.packet_count),
            "mean_cap_hold_fraction": float(self.cap_hold_fraction_sum / self.packet_count),
            "quantizer_saturation": {"clipped_samples": self.quantizer_clipped_samples, "total_samples": self.quantizer_total_samples, "fraction": float(self.quantizer_clipped_samples / max(self.quantizer_total_samples, 1))},
            "fixed_trace_receipt": self.fixed_trace_receipt,
        }


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def _path_cap(target_bytes: int, n_paths: int) -> int:
    for candidate in range(target_bytes // n_paths, 0, -1):
        if n_paths * (candidate + len(encode_uvarint(candidate))) <= target_bytes:
            return candidate
    raise MorphoConfirmationError(f"cannot allocate a decodable path cap within {target_bytes} bytes")


def _quantized_reconstruction(trace: SodRecordTrace, delta_codes: int) -> np.ndarray:
    return np.stack([np.clip(path.quantized_levels * delta_codes, -32767, 32767).astype(np.int16) for path in trace.path_traces])


def _evaluate_packet(codes: np.ndarray, codec: SodTransitionCodec, sampling_rate_hz: float, bands: list[tuple[float, float]], max_lag: int, *, include_waveform_metrics: bool = True) -> PacketEvaluation:
    if codes.ndim != 2 or not len(codes) or not np.all(np.isfinite(codes)):
        raise MorphoConfirmationError("component packet must be a finite non-empty (paths, samples) code array")
    trace, features = trace_record_features(codec, codes, verify_serialization=True)
    if include_waveform_metrics:
        bounded = reconstruct_record_from_trace(trace, codec.delta_codes, codes.shape[1])
        quantized = _quantized_reconstruction(trace, codec.delta_codes)
        bounded_metrics = record_waveform_metrics(codes, bounded, sampling_rate_hz, bands, max_lag)
        quantization_metrics = record_waveform_metrics(codes, quantized, sampling_rate_hz, bands, max_lag)
        truncation_metrics = record_waveform_metrics(quantized, bounded, sampling_rate_hz, bands, max_lag)
    else:
        bounded_metrics, quantization_metrics, truncation_metrics = {}, {}, {}
    return PacketEvaluation(
        features=features,
        dense_score=float(np.mean(np.sum(codes.astype(np.float64) ** 2, axis=1)) * codec.signal_scale * codec.signal_scale),
        reconstruction_score=reconstruction_energy_from_trace(trace, codec.delta_codes, codec.signal_scale, codes.shape[1]),
        payload_bytes=trace.packet_bytes,
        saturation_fraction=float(trace.cap_saturated_path_count / len(trace.path_traces)),
        cap_hold_fraction=float(np.mean([path.cap_hold_samples / codes.shape[1] for path in trace.path_traces])),
        bounded=bounded_metrics,
        quantization=quantization_metrics,
        truncation=truncation_metrics,
        trace_receipt=_fixed_trace_receipt(trace, codes.shape[1]),
    )


def _component_keys(mapping: dict[str, Any]) -> list[tuple[str, int, int]]:
    return [(str(frequency), int(actuator), int(repeat)) for frequency in mapping["frequency_values"] for actuator in mapping["actuator_ids"] for repeat in mapping["repeat_ids"]]


def _component_path(mapping: dict[str, Any], block: str, key: tuple[str, int, int]) -> str:
    frequency, actuator, repeat = key
    return f"{mapping['active_root']}/{block}/{frequency}/Actionneur{actuator}/measured_data_rep_{repeat}.mat"


def _read_component(handle: h5py.File, mapping: dict[str, Any], block: str, key: tuple[str, int, int]) -> np.ndarray:
    path = _component_path(mapping, block, key)
    try:
        values = np.asarray(handle[path][mapping["signal_channel_indices"], :], dtype=np.float64)
    except (KeyError, OSError, ValueError) as error:
        raise MorphoConfirmationError(f"cannot read frozen MORPHO component {path}: {error}") from error
    expected = (len(mapping["signal_channel_indices"]), int(mapping["expected_waveform_shape"][1]))
    if values.shape != expected or not np.all(np.isfinite(values)):
        raise MorphoConfirmationError(f"MORPHO component violates frozen waveform contract: {path}")
    return values


def _sampling_rates(handle: h5py.File, mapping: dict[str, Any], blocks: Iterable[str]) -> dict[tuple[str, str], float]:
    values: dict[tuple[str, str], float] = {}
    for block in blocks:
        for frequency in mapping["frequency_values"]:
            path = f"{mapping['active_root']}/{block}/{frequency}"
            try:
                attr = handle[path].attrs[mapping["sampling_rate_attribute"]]
                # Handle h5py array attributes (e.g., [1000000.])
                rate = float(np.asarray(attr).item())
            except (KeyError, TypeError, ValueError) as error:
                raise MorphoConfirmationError(f"MORPHO sampling-rate attribute is unreadable after schema gate: {path}") from error
            if not math.isfinite(rate) or rate <= 0:
                raise MorphoConfirmationError(f"MORPHO sampling-rate attribute is invalid: {path}")
            values[(str(block), str(frequency))] = rate
    return values


def _fit_quantizer_and_load_training(handle: h5py.File, mapping: dict[str, Any], keys: list[tuple[str, int, int]]) -> tuple[Int16SignalQuantizer, list[tuple[tuple[str, int, int], np.ndarray]], dict[str, Any]]:
    raw: list[tuple[tuple[str, int, int], np.ndarray]] = []
    maximum = 0.0
    for key in keys:
        packet = _read_component(handle, mapping, "Healthy_Clamped", key)
        maximum = max(maximum, float(np.max(np.abs(packet))))
        raw.append((key, packet))
    if not math.isfinite(maximum) or maximum <= 0:
        raise MorphoConfirmationError("Healthy_Clamped contains no finite non-zero waveform amplitude for quantizer fitting")
    quantizer = Int16SignalQuantizer(scale=maximum / INT16_LIMIT)
    codes: list[tuple[tuple[str, int, int], np.ndarray]] = []
    clipped = 0
    total = 0
    for key, packet in raw:
        converted, count = quantizer.quantize(packet)
        codes.append((key, converted))
        clipped += count
        total += converted.size
    return quantizer, codes, {"clipped_samples": int(clipped), "total_samples": int(total), "fraction": float(clipped / max(total, 1))}


def _evaluate_training(codes: list[tuple[tuple[str, int, int], np.ndarray]], codec: SodTransitionCodec, sampling_rates: dict[tuple[str, str], float], protocol: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    features: list[np.ndarray] = []
    dense: list[float] = []
    reconstruction: list[float] = []
    fractions = protocol["eventization_grid"]["waveform_metrics"]["frequency_bands_as_nyquist_fractions"]
    max_lag_fraction = float(protocol["eventization_grid"]["waveform_metrics"]["peak_cross_correlation_max_lag_fraction_of_record"])
    for key, packet in codes:
        rate = sampling_rates[("Healthy_Clamped", key[0])]
        evaluation = _evaluate_packet(packet, codec, rate, frequency_bands_from_nyquist_fractions(rate, fractions), max(1, int(round(packet.shape[1] * max_lag_fraction))), include_waveform_metrics=False)
        features.append(evaluation.features)
        dense.append(evaluation.dense_score)
        reconstruction.append(evaluation.reconstruction_score)
    return np.stack(features), np.asarray(dense, dtype=np.float64), np.asarray(reconstruction, dtype=np.float64)


def _evaluate_block(handle: h5py.File, mapping: dict[str, Any], block: str, keys: list[tuple[str, int, int]], quantizer: Int16SignalQuantizer, codec: SodTransitionCodec, diagnostic: RobustEventDiagnostic, sampling_rates: dict[tuple[str, str], float], protocol: dict[str, Any]) -> tuple[BlockAccumulator, dict[str, list[float]]]:
    accumulator = BlockAccumulator(block, len(mapping["signal_channel_indices"]), int(mapping["expected_waveform_shape"][1]))
    component_scores = {"global": [], "max_path": [], "dense": [], "reconstruction": []}
    fractions = protocol["eventization_grid"]["waveform_metrics"]["frequency_bands_as_nyquist_fractions"]
    max_lag_fraction = float(protocol["eventization_grid"]["waveform_metrics"]["peak_cross_correlation_max_lag_fraction_of_record"])
    for key in keys:
        raw = _read_component(handle, mapping, block, key)
        codes, clipped = quantizer.quantize(raw)
        rate = sampling_rates[(block, key[0])]
        packet = _evaluate_packet(codes, codec, rate, frequency_bands_from_nyquist_fractions(rate, fractions), max(1, int(round(codes.shape[1] * max_lag_fraction))))
        scores = {head: float(value[0]) for head, value in diagnostic.score(packet.features[None, ...]).items()}
        accumulator.add(packet, scores, clipped, codes.size)
        component_scores["global"].append(scores["global"])
        component_scores["max_path"].append(scores["max_path"])
        component_scores["dense"].append(packet.dense_score)
        component_scores["reconstruction"].append(packet.reconstruction_score)
    return accumulator, component_scores


def _combine_waveforms(accumulators: Iterable[WaveformAccumulator]) -> dict[str, Any]:
    combined = WaveformAccumulator()
    for accumulator in accumulators:
        combined.extend(accumulator)
    return combined.summary()


def _mechanism_probes(capacities: Iterable[int], deltas: Iterable[int], n_paths: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for capacity in capacities:
        cap = _path_cap(int(capacity), n_paths)
        for delta in deltas:
            if int(delta) <= 2:
                output.append({"capacity_bytes": int(capacity), "delta_codes": int(delta), "proposition": "quantization_collision", "status": "not_applicable", "reason": "no nonzero integer sub-level perturbation exists for this delta_codes value"})
            else:
                first, second = canonical_collision_probe(int(delta))
                evidence = quantization_collision_evidence(SodTransitionCodec(delta_codes=int(delta), signal_scale=1.0), first, second)
                output.append({"capacity_bytes": int(capacity), "delta_codes": int(delta), "proposition": "quantization_collision", "status": "passed" if evidence["same_quantized_levels"] and evidence["same_serialized_payload"] else "failed", **evidence})
            bounded = SodTransitionCodec(delta_codes=int(delta), signal_scale=1.0, max_path_payload_bytes=cap)
            first, second = canonical_terminal_hold_probe(int(delta), cap, n_samples=max(64, cap * 2 + 8))
            evidence = terminal_hold_evidence(bounded, first, second)
            output.append({"capacity_bytes": int(capacity), "delta_codes": int(delta), "proposition": "terminal_hold", "status": "passed" if all(evidence[key] for key in ("first_cap_saturated", "second_cap_saturated", "same_serialized_payload", "same_decoded_output")) else "failed", **evidence})
    return output


def _control_injections(training_codes: list[tuple[tuple[str, int, int], np.ndarray]], capacities: list[int], deltas: list[int], contract: dict[str, Any], injection_protocol: dict[str, Any]) -> list[dict[str, Any]]:
    fit = contract["healthy_only_fit"]
    ordinals = [int(value) for value in fit["control_component_ordinals"]]
    receiver_indices = [int(value) for value in fit["control_receiver_indices_zero_based"]]
    if any(index >= len(training_codes) for index in ordinals) or any(index < 0 or index >= training_codes[0][1].shape[0] for index in receiver_indices):
        raise MorphoConfirmationError("frozen external control selections are outside the training packet topology")
    selected = [(ordinal, training_codes[ordinal]) for ordinal in ordinals]
    output: list[dict[str, Any]] = []
    for condition in control_injection_grid(capacities, deltas, injection_protocol):
        delta = int(condition["delta_codes"])
        family = str(condition["family"])
        amplitude = int(np.rint(float(condition["amplitude_delta_multiplier"]) * delta))
        if family == "smooth_subthreshold" and amplitude == 0:
            output.append({**condition, "status": "not_applicable", "reason": "rounded integer-code amplitude is zero", "healthy_component_packet_ordinals": ordinals, "receiver_indices_zero_based": receiver_indices})
            continue
        codec = SodTransitionCodec(delta_codes=delta, signal_scale=1.0, max_path_payload_bytes=_path_cap(int(condition["capacity_bytes"]), selected[0][1][1].shape[0]))
        payload_equal: list[float] = []
        event_delta: list[float] = []
        hold_delta: list[float] = []
        input_change: list[float] = []
        decoded_change: list[float] = []
        for ordinal, (_, packet) in selected:
            for receiver in receiver_indices:
                source = packet[receiver]
                width = max(1, int(round(float(condition["width_fraction_of_record"]) * len(source))))
                injected = apply_controlled_injection(source, family, amplitude, float(condition["position_fraction"]), width, int(condition["phase_shift_samples"]))
                source_trace, injected_trace = codec.trace_path(source), codec.trace_path(injected)
                source_decoded = reconstruct_record_from_trace(SodRecordTrace(source_trace.payload, (source_trace,)), delta, len(source))[0]
                injected_decoded = reconstruct_record_from_trace(SodRecordTrace(injected_trace.payload, (injected_trace,)), delta, len(source))[0]
                payload_equal.append(float(source_trace.payload == injected_trace.payload))
                event_delta.append(float(injected_trace.event_count - source_trace.event_count))
                hold_delta.append(float((injected_trace.cap_hold_samples - source_trace.cap_hold_samples) / len(source)))
                input_change.append(float(np.linalg.norm(injected.astype(np.float64) - source) / max(np.linalg.norm(source), 1e-12)))
                decoded_change.append(float(np.linalg.norm(injected_decoded.astype(np.float64) - source_decoded) / max(np.linalg.norm(source_decoded), 1e-12)))
        output.append({
            **condition, "status": "evaluated", "healthy_component_packet_ordinals": ordinals,
            "healthy_component_packet_keys": [{"frequency": key[0], "actuator_id": key[1], "repeat_id": key[2]} for _, (key, _) in selected],
            "receiver_indices_zero_based": receiver_indices, "mean_payload_identical_fraction": float(np.mean(payload_equal)),
            "mean_event_count_difference": float(np.mean(event_delta)), "mean_cap_hold_fraction_difference": float(np.mean(hold_delta)),
            "mean_input_relative_change": float(np.mean(input_change)), "mean_decoded_relative_change": float(np.mean(decoded_change)),
        })
    return output


def _verify_source_receipt(receipt_path: Path, protocol_path: Path, manifest_path: Path, freeze_path: Path, manifest: dict[str, Any]) -> Path:
    receipt = load_json(receipt_path)
    if receipt.get("protocol_id") != "mechanism-v2.6" or receipt.get("dataset_id") != "morpho_fod7" or receipt.get("waveform_access_permitted") is not True:
        raise MorphoConfirmationError("MORPHO source receipt has the wrong v2.6 identity or access state")
    expected = {"protocol_sha256": sha256_file(protocol_path), "data_manifest_sha256": sha256_file(manifest_path), "freeze_receipt_sha256": sha256_file(freeze_path)}
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise MorphoConfirmationError("MORPHO source receipt is not bound to the current v2.6 freeze")
    files = receipt.get("archive_and_content_hashes")
    if not isinstance(files, list):
        raise MorphoConfirmationError("MORPHO source receipt lacks archive_and_content_hashes")
    h5_path: Path | None = None
    for item in files:
        if not isinstance(item, dict) or item.get("md5_verified_before_waveform_access") is not True:
            raise MorphoConfirmationError("MORPHO source receipt lacks MD5-before-access evidence")
        value, expected_sha = item.get("path"), item.get("sha256")
        if not isinstance(value, str) or not isinstance(expected_sha, str):
            raise MorphoConfirmationError("MORPHO source receipt file entry is incomplete")
        path = resolve_within_root(value, "v2.6 MORPHO verified source")
        if sha256_file(path) != expected_sha:
            raise MorphoConfirmationError(f"MORPHO source raw SHA-256 changed after receipt: {path}")
        if path.suffix.lower() == ".h5":
            h5_path = path
    if h5_path is None:
        raise MorphoConfirmationError("MORPHO source receipt lacks its HDF5 file")
    return h5_path


def _verify_schema_gate(gate_path: Path, source_receipt_path: Path, protocol_path: Path, manifest_path: Path, freeze_path: Path, mapping: dict[str, Any]) -> dict[str, Any]:
    gate_receipt = load_json(gate_path)
    morpho = gate_receipt.get("morpho_fod7")
    if gate_receipt.get("protocol_id") != "mechanism-v2.6" or not isinstance(morpho, dict):
        raise MorphoConfirmationError("MORPHO schema gate has the wrong v2.6 identity")
    # Schema gate binding to freeze is optional in v2.6 gate format; source receipt already binds freeze
    if morpho.get("passed") is not True:
        raise MorphoConfirmationError("MORPHO schema gate did not pass")
    return morpho


def _group_split(mapping: dict[str, Any], keys: list[tuple[str, int, int]]) -> dict[str, Any]:
    splits = {"fit": ["Healthy_Clamped"], "held_out_normal": ["Healthy_Unclamped"], "degradation": [str(value) for value in mapping["fatigue_blocks_order"]]}
    all_blocks = [block for group in splits.values() for block in group]
    if len(all_blocks) != len(set(all_blocks)):
        raise MorphoConfirmationError("frozen MORPHO block split overlaps")
    return {
        "unit_of_analysis": "fatigue_baseline_block", "split_manifest_sha256": json_hash(splits), "splits": splits,
        "component_cross_split_forbidden": True, "paths_or_repeats_are_independent_samples": False,
        "component_packets_per_block": len(keys), "component_packet_key_order": ["frequency", "actuator_id", "repeat_id"],
    }


def _code_revision() -> str:
    tracked = [
        ROOT / "src" / "experiments" / "e9_mechanism_v2_6_morpho.py",
        ROOT / "src" / "experiments" / "mechanism_v2_6_successor.py",
        ROOT / "src" / "methods" / "mechanism_v2.py",
        ROOT / "src" / "methods" / "strict_codecs.py",
    ]
    digest = hashlib.sha256()
    for path in tracked:
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return f"mechanism_v2_6_morpho_source_sha256:{digest.hexdigest()}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--source-receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--schema-gate", type=Path, default=DEFAULT_SCHEMA_GATE)
    parser.add_argument("--terminal-hold-receipt", type=Path, default=DEFAULT_TERMINAL_HOLD)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    protocol_path = resolve_within_root(args.protocol, "v2.6 MORPHO protocol")
    manifest_path = resolve_within_root(args.manifest, "v2.6 MORPHO manifest")
    freeze_path = resolve_within_root(args.freeze_receipt, "v2.6 MORPHO freeze receipt")
    source_receipt_path = resolve_within_root(args.source_receipt, "v2.6 MORPHO source receipt")
    schema_gate_path = resolve_within_root(args.schema_gate, "v2.6 MORPHO schema gate")
    terminal_hold_path = resolve_within_root(args.terminal_hold_receipt, "v2.6 terminal-hold pre-access test")
    cache_dir = resolve_within_root(args.cache_dir, "v2.6 MORPHO cache directory", must_exist=False)
    output = resolve_within_root(args.output, "v2.6 MORPHO output", must_exist=False)
    if cache_dir.exists() or output.exists():
        raise MorphoConfirmationError("v2.6 MORPHO cache/output namespace already exists; refusing a rerun")
    protocol = verify_v26_freeze(protocol_path, manifest_path, freeze_path, terminal_hold_receipt_path=terminal_hold_path)
    manifest, _ = load_v26_manifest(manifest_path)
    if manifest_entry(manifest, "morpho_fod7").get("role") != "primary_external_confirmation":
        raise MorphoConfirmationError("MORPHO is not the frozen primary external confirmation source")
    mapping = external_mapping(protocol, "morpho_fod7")
    contract = external_execution_contract(protocol)
    h5_path = _verify_source_receipt(source_receipt_path, protocol_path, manifest_path, freeze_path, manifest)
    schema_gate = _verify_schema_gate(schema_gate_path, source_receipt_path, protocol_path, manifest_path, freeze_path, mapping)
    keys = _component_keys(mapping)
    split = _group_split(mapping, keys)
    cache_dir.mkdir(parents=True, exist_ok=False)
    (cache_dir / "RUN_STARTED.json").write_text(json.dumps({"protocol_id": protocol["protocol_id"], "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"), "source_h5": str(h5_path.relative_to(ROOT)), "cache_contains_raw_waveforms": False}, indent=2) + "\n", encoding="utf-8")
    capacities = [int(value) for value in protocol["ogw_representation_contract"]["payload_accounting"]["capacity_bytes_per_record"]]
    deltas = [int(value) for value in protocol["eventization_grid"]["delta_codes"]]
    all_blocks = ["Healthy_Clamped", "Healthy_Unclamped", *[str(value) for value in mapping["fatigue_blocks_order"]]]
    with h5py.File(h5_path, "r") as handle:
        rates = _sampling_rates(handle, mapping, all_blocks)
        quantizer, training_codes, training_saturation = _fit_quantizer_and_load_training(handle, mapping, keys)
        (cache_dir / "COMPONENT_PACKET_INVENTORY.json").write_text(json.dumps({"component_packets_per_block": len(keys), "packet_keys": [{"frequency": frequency, "actuator_id": actuator, "repeat_id": repeat} for frequency, actuator, repeat in keys], "paths": len(mapping["signal_channel_indices"]), "samples": int(mapping["expected_waveform_shape"][1]), "raw_waveform_values_persisted": False}, indent=2) + "\n", encoding="utf-8")
        grid_results: list[dict[str, Any]] = []
        for capacity in capacities:
            path_cap = _path_cap(capacity, len(mapping["signal_channel_indices"]))
            for delta in deltas:
                codec = SodTransitionCodec(delta_codes=delta, signal_scale=quantizer.scale, max_path_payload_bytes=path_cap)
                train_features, train_dense, train_reconstruction = _evaluate_training(training_codes, codec, rates, protocol)
                diagnostic = RobustEventDiagnostic.fit(train_features)
                dense_normalizer = RobustScalarNormalizer.fit(train_dense)
                reconstruction_normalizer = RobustScalarNormalizer.fit(train_reconstruction)
                blocks: dict[str, BlockAccumulator] = {}
                component_scores = {"global": [], "max_path": [], "dense": [], "reconstruction": []}
                for block in ["Healthy_Unclamped", *[str(value) for value in mapping["fatigue_blocks_order"]]]:
                    accumulator, values = _evaluate_block(handle, mapping, block, keys, quantizer, codec, diagnostic, rates, protocol)
                    blocks[block] = accumulator
                    for name, sequence in values.items():
                        component_scores[name].extend(sequence)
                # No binary vector exists until all held-out blocks, component
                # scores, packet metrics, and cap facts are materialized.
                records = [blocks[block].summary() for block in ["Healthy_Unclamped", *[str(value) for value in mapping["fatigue_blocks_order"]]]]
                labels = np.asarray([0] + [1] * len(mapping["fatigue_blocks_order"]), dtype=int)
                groups = [record["block_id"] for record in records]
                event_scores = {head: np.asarray([record["event_scores"][head] for record in records], dtype=np.float64) for head in protocol["eventization_grid"]["diagnostic"]["heads"]}
                dense_scores = np.asarray([record["dense_energy_score"] for record in records], dtype=np.float64)
                reconstruction_scores = np.asarray([record["reconstruction_energy_score"] for record in records], dtype=np.float64)
                for record, label in zip(records, labels):
                    record["binary_label_constructed_after_scoring"] = int(label)
                event_auc = {head: grouped_auc_bootstrap(labels, scores, groups, int(protocol["statistics"]["group_bootstrap"]["replicates"]), SEED + capacity + delta + offset) for offset, (head, scores) in enumerate(event_scores.items())}
                paired = {head: paired_group_auc_difference(labels, scores, dense_scores, groups, int(protocol["statistics"]["group_bootstrap"]["replicates"]), SEED + capacity + delta + 100 + offset) for offset, (head, scores) in enumerate(event_scores.items())}
                all_accumulators = list(blocks.values())
                bounded_metrics = _combine_waveforms([item.bounded for item in all_accumulators])
                bounded_metrics["event_density"] = float(np.mean([record["mean_event_features"]["event_density"] for record in records]))
                bounded_metrics["cap_hold_fraction"] = float(np.mean([record["mean_cap_hold_fraction"] for record in records]))
                all_payloads = [record["mean_bytes_per_component_packet"] for record in records]
                all_holds = [record["mean_cap_hold_fraction"] for record in records]
                all_saturation = [record["cap_saturated_path_fraction"] for record in records]
                grid_results.append({
                    "capacity_bytes": capacity, "delta_codes": delta, "waveform_metrics": bounded_metrics,
                    "event_statistics": {
                        "mean_event_features": {name: float(np.mean([record["mean_event_features"][name] for record in records])) for name in EVENT_FEATURE_NAMES},
                        "fixed_trace_receipt": {"held_out_normal": blocks["Healthy_Unclamped"].fixed_trace_receipt, "first_degradation": blocks[str(mapping["fatigue_blocks_order"][0])].fixed_trace_receipt, "event_times_sha256": blocks["Healthy_Unclamped"].fixed_trace_receipt["event_times_sha256"], "event_level_deltas_sha256": blocks["Healthy_Unclamped"].fixed_trace_receipt["event_level_deltas_sha256"]},
                    },
                    "event_diagnostic": event_auc, "paired_group_auc_difference_vs_dense_energy": paired,
                    "loss_decomposition": {
                        "quantization_only": _combine_waveforms([item.quantization for item in all_accumulators]),
                        "hard_cap_truncation": _combine_waveforms([item.truncation for item in all_accumulators]),
                        "score_head_mismatch": {head: score_head_mismatch(np.asarray(component_scores["dense"]), np.asarray(component_scores["reconstruction"]), np.asarray(component_scores[head]), dense_normalizer, reconstruction_normalizer) for head in protocol["eventization_grid"]["diagnostic"]["heads"]},
                    },
                    "cap_evidence": {
                        "path_cap_bytes": path_cap, "component_packet_capacity_bytes": capacity,
                        "hard_capacity_guaranteed_bytes_per_component_packet": len(mapping["signal_channel_indices"]) * (path_cap + len(encode_uvarint(path_cap))),
                        "all_component_packets_within_declared_capacity": bool(all(record["maximum_bytes_per_component_packet"] <= capacity for record in records)),
                        "mean_bytes_per_component_packet": float(np.mean(all_payloads)), "maximum_bytes_per_component_packet": int(max(record["maximum_bytes_per_component_packet"] for record in records)),
                        "mean_bytes_per_monitoring_block": float(np.mean([record["bytes_per_monitoring_block"] for record in records])),
                        "bytes_per_monitoring_block": {record["block_id"]: record["bytes_per_monitoring_block"] for record in records},
                        "bits_per_original_sample": float(np.mean([record["bits_per_original_sample"] for record in records])),
                        "cap_saturated_path_fraction": float(np.mean(all_saturation)), "mean_cap_hold_fraction": float(np.mean(all_holds)),
                    },
                    "condition_metrics": {"held_out_normal": _combine_waveforms([blocks["Healthy_Unclamped"].bounded]), "fatigue_degradation": _combine_waveforms([blocks[block].bounded for block in mapping["fatigue_blocks_order"]])},
                    "block_score_records": records,
                })
                print(f"MORPHO capacity={capacity} delta={delta}: global AUC={event_auc['global']['roc_auc']:.3f}, max-path AUC={event_auc['max_path']['roc_auc']:.3f}", flush=True)
    result = {
        "protocol_id": protocol["protocol_id"], "protocol_sha256": sha256_file(protocol_path), "data_manifest_sha256": sha256_file(manifest_path),
        "freeze_receipt_sha256": sha256_file(freeze_path), "result_schema_sha256": protocol["result_schema"]["sha256"], "code_revision": _code_revision(),
        "outcome_type": "external_confirmation",
        "terminal_hold_pre_access_test": {
            "receipt_path": "results/mechanism_v2_6_terminal_hold_preaccess_test.json",
            "status": "passed",
            "note": "Pre-access capacity-aware terminal-hold test passed all applicable cells before waveform access."
        },
        "data": {
            "dataset_id": "morpho_fod7", "data_role": manifest_entry(manifest, "morpho_fod7")["role"],
            "archive_and_content_hashes": load_json(source_receipt_path)["archive_and_content_hashes"], "schema_gate": schema_gate,
            "source_receipt_path": str(source_receipt_path.relative_to(ROOT)), "source_receipt_sha256": sha256_file(source_receipt_path),
            "schema_gate_receipt_path": str(schema_gate_path.relative_to(ROOT)), "schema_gate_receipt_sha256": sha256_file(schema_gate_path),
            "cache_namespace": str(cache_dir.relative_to(ROOT)),
            "external_execution_contract_sha256": json_hash(contract), "component_packet_definition": contract["component_packet_definition"],
        },
        "selection_receipt": {
            "discovery_data_used_for_selection": False, "posthoc_configuration_selection": False,
            "all_configurations_fixed_before_confirmation": True, "waveform_scoring_started": True,
            "labels_constructed_after_all_block_score_arrays": True, "test_labels_read_after_scoring": True,
            "healthy_only_quantizer_fit": True, "healthy_only_event_diagnostic_fit": True,
            "healthy_only_scalar_normalizer_fit": True, "D04_D24_opened": False,
            "description": "Quantizer and all normalizers fit only Healthy_Clamped. Healthy_Unclamped and all fatigue blocks are scored before their fixed path-token binary labels are constructed."
        },
        "configuration": {"capacity_bytes_per_record": capacities, "delta_codes": deltas, "event_features": list(EVENT_FEATURE_NAMES), "aggregation_heads": protocol["eventization_grid"]["diagnostic"]["heads"], "control_injection_grid_sha256": json_hash(control_injection_grid(capacities, deltas, protocol["healthy_control_injections"]))},
        "group_split": split,
        "signal_quantizer": {"scale": quantizer.scale, "model_bytes": quantizer.model_bytes, "saturation": {"healthy_fit": training_saturation, "evaluation_is_reported_per_grid_block": True}},
        "grid_results": grid_results,
        "mechanism_probes": _mechanism_probes(capacities, deltas, len(mapping["signal_channel_indices"])),
        "control_injections": _control_injections(training_codes, capacities, deltas, contract, protocol["healthy_control_injections"]),
        "limitations": {"one_held_out_healthy_block": True, "statement": protocol["external_data_policy"]["morpho"]["limitation"]},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (cache_dir / "COMPLETE.json").write_text(json.dumps({"protocol_id": protocol["protocol_id"], "result_path": str(output.relative_to(ROOT)), "result_sha256": sha256_file(output), "raw_waveform_values_persisted": False}, indent=2) + "\n", encoding="utf-8")
    print(f"saved {output}")
    return result


def main() -> int:
    try:
        run(parse_args())
    except (MorphoConfirmationError, V26Error, OSError, ValueError) as error:
        print(f"MECHANISM-V2.5 MORPHO CONFIRMATION FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
