"""Fixed mechanism measurements for bounded level-crossing eventization.

This module deliberately contains no dataset-specific label handling or
configuration search.  It converts a preconfigured :class:`SodTransitionCodec`
into auditable event statistics, representation probes, and record-level
diagnostics whose calibration uses healthy records only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from scipy.signal import correlate, correlation_lags
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

from src.methods.strict_codecs import SodPathTrace, SodRecordTrace, SodTransitionCodec


EVENT_FEATURE_NAMES = (
    "event_density",
    "signed_total_variation",
    "event_time_centroid",
    "event_time_spread",
    "cap_hold_fraction",
)


class MechanismInvariantError(ValueError):
    """Raised when a frozen mechanism-v2 data invariant is violated."""


def _as_record_array(values: np.ndarray, context: str) -> np.ndarray:
    values = np.asarray(values)
    if values.ndim != 2 or values.shape[0] <= 0 or values.shape[1] <= 0:
        raise MechanismInvariantError(f"{context} must have shape (paths, samples) with non-zero dimensions")
    if not np.all(np.isfinite(values)):
        raise MechanismInvariantError(f"{context} contains non-finite values")
    return values


def _robust_scale(values: np.ndarray, axis: int | tuple[int, ...]) -> tuple[np.ndarray, np.ndarray]:
    center = np.median(values, axis=axis)
    expanded_center = center
    if isinstance(axis, tuple):
        for position in sorted(axis):
            expanded_center = np.expand_dims(expanded_center, axis=position)
    else:
        expanded_center = np.expand_dims(expanded_center, axis=axis)
    mad = np.median(np.abs(values - expanded_center), axis=axis)
    return center, np.maximum(1.4826 * mad, 1e-12)


def event_features_from_trace(trace: SodPathTrace, n_samples: int) -> np.ndarray:
    """Return the five predeclared event-native path features.

    Event time moments are weighted by absolute quantized level changes and
    normalized to the inclusive sample range.  A path with no transmitted
    changes has a deterministic centroid/spread of zero rather than a value
    estimated from another path or split.
    """

    if n_samples <= 0:
        raise MechanismInvariantError("n_samples must be positive")
    times = trace.transmitted_event_indices.astype(np.float64, copy=False)
    deltas = trace.transmitted_event_level_deltas.astype(np.float64, copy=False)
    density = float(len(times) / n_samples)
    signed_variation = float(np.sum(deltas) / n_samples)
    if len(times):
        normalized_times = times / max(n_samples - 1, 1)
        weights = np.abs(deltas)
        total_weight = float(np.sum(weights))
        if total_weight > 0:
            centroid = float(np.sum(normalized_times * weights) / total_weight)
            spread = float(np.sqrt(np.sum(weights * (normalized_times - centroid) ** 2) / total_weight))
        else:
            centroid = 0.0
            spread = 0.0
    else:
        centroid = 0.0
        spread = 0.0
    return np.asarray(
        [density, signed_variation, centroid, spread, trace.cap_hold_samples / n_samples],
        dtype=np.float64,
    )


def trace_record_features(
    codec: SodTransitionCodec,
    record_codes: np.ndarray,
    verify_serialization: bool = False,
) -> tuple[SodRecordTrace, np.ndarray]:
    """Trace a record once and return per-path event features from that packet."""

    record_codes = _as_record_array(record_codes, "record_codes").astype(np.int16, copy=False)
    trace = codec.trace_record(record_codes)
    if verify_serialization and trace.payload != codec.encode_record(record_codes):
        raise MechanismInvariantError("SoD trace payload differs from serialized record payload")
    features = np.vstack([event_features_from_trace(path_trace, record_codes.shape[1]) for path_trace in trace.path_traces])
    return trace, features


def trace_summary(trace: SodPathTrace, n_samples: int) -> dict[str, float | int | bool | None]:
    """Produce compact JSON-safe audit facts without copying full event arrays."""

    if n_samples <= 0:
        raise MechanismInvariantError("n_samples must be positive")
    return {
        "initial_quantized_level": None if not len(trace.transmitted_levels) else int(trace.transmitted_levels[0]),
        "final_transmitted_quantized_level": None if not len(trace.transmitted_levels) else int(trace.transmitted_levels[-1]),
        "candidate_event_count": trace.candidate_event_count,
        "transmitted_event_count": trace.event_count,
        "last_transmitted_event_index": trace.last_transmitted_event_index,
        "packet_bytes": trace.packet_bytes,
        "packet_cap_bytes": trace.packet_cap_bytes,
        "packet_utilization": trace.packet_utilization,
        "cap_saturated": trace.cap_saturated,
        "terminal_hold_samples": trace.terminal_hold_samples,
        "cap_hold_samples": trace.cap_hold_samples,
        "cap_hold_fraction": float(trace.cap_hold_samples / n_samples),
    }


def reconstruct_path_from_trace(trace: SodPathTrace, delta_codes: int, n_samples: int) -> np.ndarray:
    """Decode a trace directly, preserving the codec's terminal-hold rule."""

    if n_samples < 0:
        raise MechanismInvariantError("n_samples must be non-negative")
    if n_samples == 0:
        return np.empty(0, dtype=np.int16)
    if not len(trace.transmitted_levels):
        raise MechanismInvariantError("non-empty path trace lacks an initial level")
    starts = np.concatenate((np.array([0], dtype=np.int64), trace.transmitted_event_indices))
    ends = np.concatenate((starts[1:], np.array([n_samples], dtype=np.int64)))
    output = np.empty(n_samples, dtype=np.int64)
    for start, end, level in zip(starts, ends, trace.transmitted_levels):
        output[int(start):int(end)] = int(level) * delta_codes
    return np.clip(output, -32767, 32767).astype(np.int16)


def reconstruct_record_from_trace(trace: SodRecordTrace, delta_codes: int, n_samples: int) -> np.ndarray:
    """Decode a record trace without re-parsing its already audited payload."""

    return np.stack([reconstruct_path_from_trace(path, delta_codes, n_samples) for path in trace.path_traces])


def reconstruction_energy_from_trace(trace: SodRecordTrace, delta_codes: int, signal_scale: float, n_samples: int) -> float:
    """Return the codec's record reconstruction-energy score from trace segments."""

    if n_samples <= 0:
        raise MechanismInvariantError("n_samples must be positive")
    total = 0.0
    for path in trace.path_traces:
        if not len(path.transmitted_levels):
            continue
        starts = np.concatenate((np.array([0], dtype=np.int64), path.transmitted_event_indices))
        ends = np.concatenate((starts[1:], np.array([n_samples], dtype=np.int64)))
        levels = np.clip(path.transmitted_levels * delta_codes, -32767, 32767).astype(np.float64)
        lengths = (ends - starts).astype(np.float64)
        total += float(np.dot(lengths, levels * levels))
    return float(total * signal_scale * signal_scale / max(len(trace.path_traces), 1))


@dataclass(frozen=True)
class RobustEventDiagnostic:
    """Healthy-only robust normalizer with fixed global and max-path heads."""

    global_median: np.ndarray
    global_scale: np.ndarray
    path_median: np.ndarray
    path_scale: np.ndarray

    @classmethod
    def fit(cls, healthy_features: np.ndarray) -> "RobustEventDiagnostic":
        healthy_features = np.asarray(healthy_features, dtype=np.float64)
        if healthy_features.ndim != 3 or healthy_features.shape[0] == 0:
            raise MechanismInvariantError("healthy event features must have shape (records, paths, features)")
        if healthy_features.shape[2] != len(EVENT_FEATURE_NAMES):
            raise MechanismInvariantError("healthy event feature count differs from the frozen feature list")
        if not np.all(np.isfinite(healthy_features)):
            raise MechanismInvariantError("healthy event features contain non-finite values")
        global_features = np.mean(healthy_features, axis=1)
        global_median, global_scale = _robust_scale(global_features, axis=0)
        path_median, path_scale = _robust_scale(healthy_features, axis=0)
        return cls(global_median, global_scale, path_median, path_scale)

    def score(self, features: np.ndarray) -> dict[str, np.ndarray]:
        features = np.asarray(features, dtype=np.float64)
        if features.ndim != 3 or features.shape[1:] != self.path_median.shape:
            raise MechanismInvariantError("event feature shape differs from the healthy calibration tensor")
        if not np.all(np.isfinite(features)):
            raise MechanismInvariantError("event features contain non-finite values")
        global_features = np.mean(features, axis=1)
        global_z = np.abs((global_features - self.global_median) / self.global_scale)
        path_z = np.abs((features - self.path_median) / self.path_scale)
        return {
            "global": np.max(global_z, axis=1),
            "max_path": np.max(path_z, axis=(1, 2)),
        }


@dataclass(frozen=True)
class RobustScalarNormalizer:
    """One-dimensional healthy-only robust score normalizer."""

    median: float
    scale: float

    @classmethod
    def fit(cls, healthy_values: np.ndarray) -> "RobustScalarNormalizer":
        healthy_values = np.asarray(healthy_values, dtype=np.float64)
        if healthy_values.ndim != 1 or not len(healthy_values) or not np.all(np.isfinite(healthy_values)):
            raise MechanismInvariantError("healthy scalar values must be a non-empty finite vector")
        median = float(np.median(healthy_values))
        mad = float(np.median(np.abs(healthy_values - median)))
        return cls(median, max(1.4826 * mad, 1e-12))

    def score(self, values: np.ndarray) -> np.ndarray:
        values = np.asarray(values, dtype=np.float64)
        if not np.all(np.isfinite(values)):
            raise MechanismInvariantError("scalar values contain non-finite values")
        return np.abs((values - self.median) / self.scale)


def waveform_energy_score(records: np.ndarray) -> np.ndarray:
    """Fixed reconstruction head used only for score-head mismatch reporting."""

    records = np.asarray(records, dtype=np.float64)
    if records.ndim != 3 or records.shape[0] == 0:
        raise MechanismInvariantError("records must have shape (records, paths, samples)")
    if not np.all(np.isfinite(records)):
        raise MechanismInvariantError("records contain non-finite values")
    return np.mean(np.sum(records * records, axis=2), axis=1)


def _path_correlation(source: np.ndarray, reconstructed: np.ndarray) -> float:
    source = source.astype(np.float64, copy=False)
    reconstructed = reconstructed.astype(np.float64, copy=False)
    source_centered = source - np.mean(source)
    reconstructed_centered = reconstructed - np.mean(reconstructed)
    denominator = float(np.linalg.norm(source_centered) * np.linalg.norm(reconstructed_centered))
    if denominator == 0.0:
        return 1.0 if np.array_equal(source, reconstructed) else 0.0
    return float(np.dot(source_centered, reconstructed_centered) / denominator)


def _path_peak_delay(source: np.ndarray, reconstructed: np.ndarray, max_lag_samples: int) -> int:
    if max_lag_samples < 0:
        raise MechanismInvariantError("max_lag_samples must be non-negative")
    source = source.astype(np.float64, copy=False)
    reconstructed = reconstructed.astype(np.float64, copy=False)
    source = source - np.mean(source)
    reconstructed = reconstructed - np.mean(reconstructed)
    source_norm = float(np.linalg.norm(source))
    reconstructed_norm = float(np.linalg.norm(reconstructed))
    if source_norm == 0.0 or reconstructed_norm == 0.0:
        return 0
    correlation = correlate(source, reconstructed, mode="full", method="fft") / (source_norm * reconstructed_norm)
    lags = correlation_lags(len(source), len(reconstructed), mode="full")
    eligible = np.abs(lags) <= min(max_lag_samples, len(source) - 1)
    local = np.flatnonzero(eligible)
    return int(lags[local[np.argmax(np.abs(correlation[local]))]])


def _path_band_retention(
    source: np.ndarray,
    reconstructed: np.ndarray,
    sampling_rate_hz: float,
    frequency_bands_hz: Sequence[tuple[float, float]],
) -> np.ndarray:
    if sampling_rate_hz <= 0:
        raise MechanismInvariantError("sampling_rate_hz must be positive")
    frequencies = np.fft.rfftfreq(len(source), d=1.0 / sampling_rate_hz)
    source_power = np.abs(np.fft.rfft(source.astype(np.float64, copy=False))) ** 2
    reconstructed_power = np.abs(np.fft.rfft(reconstructed.astype(np.float64, copy=False))) ** 2
    retained = []
    for low, high in frequency_bands_hz:
        if not (0 <= low < high <= sampling_rate_hz / 2):
            raise MechanismInvariantError("frequency bands must lie within the Nyquist range")
        mask = (frequencies >= low) & (frequencies < high)
        source_energy = float(np.sum(source_power[mask]))
        reconstructed_energy = float(np.sum(reconstructed_power[mask]))
        retained.append(1.0 if source_energy == 0.0 and reconstructed_energy == 0.0 else reconstructed_energy / max(source_energy, 1e-12))
    return np.asarray(retained, dtype=np.float64)


def record_waveform_metrics(
    source: np.ndarray,
    reconstructed: np.ndarray,
    sampling_rate_hz: float,
    frequency_bands_hz: Sequence[tuple[float, float]],
    max_lag_samples: int,
) -> dict[str, float | dict[str, float]]:
    """Report every frozen waveform metric for one monitoring record.

    Per-path values are aggregated deterministically: mean for correlation,
    relative error and band retention; median and mean absolute value for
    signed peak cross-correlation delay.
    """

    source = _as_record_array(source, "source")
    reconstructed = _as_record_array(reconstructed, "reconstructed")
    if source.shape != reconstructed.shape:
        raise MechanismInvariantError("source and reconstructed records must share shape")
    correlations = []
    relative_errors = []
    delays = []
    retentions = []
    for source_path, reconstructed_path in zip(source, reconstructed):
        correlations.append(_path_correlation(source_path, reconstructed_path))
        relative_errors.append(float(np.linalg.norm(source_path - reconstructed_path) / max(np.linalg.norm(source_path), 1e-12)))
        delays.append(_path_peak_delay(source_path, reconstructed_path, max_lag_samples))
        retentions.append(_path_band_retention(source_path, reconstructed_path, sampling_rate_hz, frequency_bands_hz))
    retention_matrix = np.vstack(retentions)
    named_retention = {
        f"{int(low)}-{int(high)}Hz": float(value)
        for (low, high), value in zip(frequency_bands_hz, np.mean(retention_matrix, axis=0))
    }
    return {
        "waveform_correlation_mean": float(np.mean(correlations)),
        "relative_error_mean": float(np.mean(relative_errors)),
        "peak_cross_correlation_delay_samples_median": float(np.median(delays)),
        "peak_cross_correlation_delay_samples_mean_absolute": float(np.mean(np.abs(delays))),
        "frequency_band_retention": named_retention,
    }


def score_head_mismatch(
    dense_scores: np.ndarray,
    reconstruction_scores: np.ndarray,
    event_scores: np.ndarray,
    dense_normalizer: RobustScalarNormalizer,
    reconstruction_normalizer: RobustScalarNormalizer,
) -> dict[str, float | None]:
    """Measure fixed disagreement between dense, reconstructed, and event heads.

    The two scalar normalizers must be fitted on healthy training records.
    Event scores are already healthy-normalized by :class:`RobustEventDiagnostic`.
    No labels enter this calculation.
    """

    dense_scores = np.asarray(dense_scores, dtype=np.float64)
    reconstruction_scores = np.asarray(reconstruction_scores, dtype=np.float64)
    event_scores = np.asarray(event_scores, dtype=np.float64)
    if not (dense_scores.shape == reconstruction_scores.shape == event_scores.shape) or dense_scores.ndim != 1:
        raise MechanismInvariantError("score heads must be equal-length vectors")
    dense_z = dense_normalizer.score(dense_scores)
    reconstructed_z = reconstruction_normalizer.score(reconstruction_scores)
    if len(dense_scores) < 2 or np.ptp(reconstructed_z) == 0.0 or np.ptp(event_scores) == 0.0:
        rank_correlation: float | None = None
    else:
        rank_correlation = float(spearmanr(reconstructed_z, event_scores).statistic)
    return {
        "dense_vs_reconstruction_mean_absolute_score_difference": float(np.mean(np.abs(dense_z - reconstructed_z))),
        "reconstruction_vs_event_mean_absolute_score_difference": float(np.mean(np.abs(reconstructed_z - event_scores))),
        "reconstruction_vs_event_spearman": rank_correlation,
    }


def quantization_collision_evidence(
    codec: SodTransitionCodec,
    baseline_codes: np.ndarray,
    perturbed_codes: np.ndarray,
) -> dict[str, float | int | bool]:
    """Verify the exact condition under which two inputs serialize identically."""

    baseline = np.asarray(baseline_codes, dtype=np.int16)
    perturbed = np.asarray(perturbed_codes, dtype=np.int16)
    if baseline.shape != perturbed.shape or baseline.ndim != 1 or not len(baseline):
        raise MechanismInvariantError("collision inputs must be equal-length non-empty paths")
    baseline_trace = codec.trace_path(baseline)
    perturbed_trace = codec.trace_path(perturbed)
    same_levels = bool(np.array_equal(baseline_trace.quantized_levels, perturbed_trace.quantized_levels))
    same_payload = baseline_trace.payload == perturbed_trace.payload
    return {
        "same_quantized_levels": same_levels,
        "same_serialized_payload": same_payload,
        "same_transmitted_event_times": bool(
            np.array_equal(baseline_trace.transmitted_event_indices, perturbed_trace.transmitted_event_indices)
        ),
        "same_transmitted_event_level_deltas": bool(
            np.array_equal(baseline_trace.transmitted_event_level_deltas, perturbed_trace.transmitted_event_level_deltas)
        ),
        "maximum_input_difference_codes": int(np.max(np.abs(baseline.astype(np.int32) - perturbed.astype(np.int32)))),
    }


def terminal_hold_evidence(
    codec: SodTransitionCodec,
    first_codes: np.ndarray,
    second_codes: np.ndarray,
) -> dict[str, int | bool]:
    """Verify cap-induced suffix equivalence for a predeclared input pair."""

    first = np.asarray(first_codes, dtype=np.int16)
    second = np.asarray(second_codes, dtype=np.int16)
    if first.shape != second.shape or first.ndim != 1 or not len(first):
        raise MechanismInvariantError("terminal-hold inputs must be equal-length non-empty paths")
    first_trace = codec.trace_path(first)
    second_trace = codec.trace_path(second)
    first_decoded = codec.decode_path(first_trace.payload, len(first))
    second_decoded = codec.decode_path(second_trace.payload, len(second))
    return {
        "first_cap_saturated": first_trace.cap_saturated,
        "second_cap_saturated": second_trace.cap_saturated,
        "same_serialized_payload": first_trace.payload == second_trace.payload,
        "same_decoded_output": bool(np.array_equal(first_decoded, second_decoded)),
        "first_cap_hold_samples": first_trace.cap_hold_samples,
        "second_cap_hold_samples": second_trace.cap_hold_samples,
        "suffix_input_difference_codes": int(np.max(np.abs(first.astype(np.int32) - second.astype(np.int32)))),
    }


def canonical_collision_probe(delta_codes: int, n_samples: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """Build a continuous-looking sub-level perturbation with identical levels.

    The baseline is at the middle of a quantization bin.  For integer code
    domains with ``delta_codes <= 2`` no nonzero sub-level perturbation exists,
    so callers must report that condition as not applicable rather than claim
    a collision.
    """

    if delta_codes <= 2:
        raise MechanismInvariantError("a nonzero integer sub-level probe requires delta_codes greater than two")
    if n_samples < 4:
        raise MechanismInvariantError("collision probe requires at least four samples")
    amplitude = max(1, (delta_codes - 1) // 3)
    baseline = np.zeros(n_samples, dtype=np.int16)
    phase = np.linspace(0.0, 2.0 * np.pi, n_samples, endpoint=False)
    perturbed = np.rint(amplitude * np.sin(phase)).astype(np.int16)
    return baseline, perturbed


def canonical_terminal_hold_probe(delta_codes: int, max_path_payload_bytes: int, n_samples: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """Build two paths that diverge only after a deterministic cap is reached."""

    if n_samples < 8:
        raise MechanismInvariantError("terminal-hold probe requires at least eight samples")
    codec = SodTransitionCodec(delta_codes=delta_codes, signal_scale=1.0, max_path_payload_bytes=max_path_payload_bytes)
    prefix = np.zeros(n_samples, dtype=np.int16)
    # Repeated one-level changes force short timestamp/value events until the
    # fixed byte cap rejects one of them.
    for index in range(1, n_samples):
        prefix[index] = delta_codes if index % 2 else 0
    trace = codec.trace_path(prefix)
    if not trace.cap_saturated:
        raise MechanismInvariantError("canonical terminal-hold probe did not reach the configured cap")
    divergence = max(trace.last_transmitted_event_index + 1, 2)
    first = prefix.copy()
    second = prefix.copy()
    first[divergence:] = np.int16(delta_codes)
    second[divergence:] = np.int16(-delta_codes)
    return first, second


def apply_controlled_injection(
    path_codes: np.ndarray,
    family: str,
    amplitude_codes: int,
    position_fraction: float,
    width_samples: int,
    phase_shift_samples: int = 0,
) -> np.ndarray:
    """Apply one fixed healthy-only representation probe in code space."""

    path_codes = np.asarray(path_codes, dtype=np.int16)
    if path_codes.ndim != 1 or not len(path_codes):
        raise MechanismInvariantError("control injection expects a non-empty path")
    if amplitude_codes < 0 or not 0.0 <= position_fraction <= 1.0 or width_samples <= 0:
        raise MechanismInvariantError("invalid control injection parameters")
    result = path_codes.astype(np.int32, copy=True)
    center = int(round(position_fraction * (len(result) - 1)))
    start = max(0, center - width_samples // 2)
    stop = min(len(result), start + width_samples)
    if family == "sparse_abrupt":
        result[start:stop] += amplitude_codes
    elif family == "smooth_subthreshold":
        local = np.linspace(-1.0, 1.0, stop - start, endpoint=True)
        envelope = np.exp(-0.5 * (local / 0.35) ** 2)
        result[start:stop] += np.rint(amplitude_codes * envelope).astype(np.int32)
    elif family == "phase_shift":
        result = np.roll(result, int(phase_shift_samples))
    else:
        raise MechanismInvariantError(f"unknown injection family: {family}")
    return np.clip(result, -32767, 32767).astype(np.int16)


def frequency_bands_from_nyquist_fractions(
    sampling_rate_hz: float,
    fractions: Sequence[Sequence[float]],
) -> list[tuple[float, float]]:
    """Turn protocol-stored Nyquist fractions into physical frequency bands."""

    if sampling_rate_hz <= 0:
        raise MechanismInvariantError("sampling_rate_hz must be positive")
    nyquist = sampling_rate_hz / 2.0
    bands = [(float(low) * nyquist, float(high) * nyquist) for low, high in fractions]
    if any(not (0 <= low < high <= nyquist) for low, high in bands):
        raise MechanismInvariantError("Nyquist-relative frequency bands are invalid")
    return bands


def control_injection_grid(
    capacities_bytes: Sequence[int],
    delta_codes: Sequence[int],
    injection_protocol: dict[str, object],
) -> list[dict[str, float | int | str]]:
    """Materialize the complete predeclared aggregate control grid.

    The identifiers are stable JSON objects so an audit can reject a result
    that silently drops an inconvenient family, capacity, or delta.
    """

    families = injection_protocol.get("families")
    if not isinstance(families, dict):
        raise MechanismInvariantError("control injection protocol lacks families")
    conditions: list[dict[str, float | int | str]] = []
    for capacity in capacities_bytes:
        for delta in delta_codes:
            for family, family_grid in families.items():
                if not isinstance(family_grid, dict):
                    raise MechanismInvariantError(f"control injection family {family} is invalid")
                amplitudes = family_grid.get("amplitude_delta_multipliers")
                widths = family_grid.get("width_fraction_of_record")
                positions = family_grid.get("position_fraction")
                shifts = family_grid.get("phase_shift_samples")
                if not all(isinstance(values, list) and values for values in (amplitudes, widths, positions, shifts)):
                    raise MechanismInvariantError(f"control injection family {family} has an incomplete grid")
                for amplitude in amplitudes:
                    for width in widths:
                        for position in positions:
                            for shift in shifts:
                                condition: dict[str, float | int | str] = {
                                    "capacity_bytes": int(capacity),
                                    "delta_codes": int(delta),
                                    "family": str(family),
                                    "amplitude_delta_multiplier": float(amplitude),
                                    "width_fraction_of_record": float(width),
                                    "position_fraction": float(position),
                                    "phase_shift_samples": int(shift),
                                }
                                condition["control_id"] = json.dumps(condition, sort_keys=True, separators=(",", ":"))
                                conditions.append(condition)
    return conditions


def validate_group_split(group_ids: Iterable[object], split_names: Iterable[str]) -> dict[str, list[str]]:
    """Reject path/repeat leakage by proving every group has one split only."""

    assignments: dict[str, set[str]] = {}
    for group, split in zip(group_ids, split_names):
        group_key = str(group)
        assignments.setdefault(group_key, set()).add(str(split))
    leaked = {group: sorted(splits) for group, splits in assignments.items() if len(splits) != 1}
    if leaked:
        raise MechanismInvariantError(f"group split overlap: {leaked}")
    return {group: sorted(splits) for group, splits in sorted(assignments.items())}


def chronological_group_split(group_ids: Sequence[object], fractions: tuple[float, float, float] = (0.6, 0.2, 0.2)) -> dict[str, str]:
    """Assign ordered groups contiguously to train/validation/test once."""

    if len(fractions) != 3 or not np.isclose(sum(fractions), 1.0) or any(value <= 0 for value in fractions):
        raise MechanismInvariantError("split fractions must be three positive values summing to one")
    ordered = list(dict.fromkeys(str(group) for group in group_ids))
    if len(ordered) < 3:
        raise MechanismInvariantError("at least three ordered groups are required for chronological splitting")
    train_stop = max(1, int(np.floor(len(ordered) * fractions[0])))
    validation_stop = max(train_stop + 1, int(np.floor(len(ordered) * (fractions[0] + fractions[1]))))
    validation_stop = min(validation_stop, len(ordered) - 1)
    return {
        **{group: "train" for group in ordered[:train_stop]},
        **{group: "validation" for group in ordered[train_stop:validation_stop]},
        **{group: "test" for group in ordered[validation_stop:]},
    }


def grouped_auc_bootstrap(
    labels: np.ndarray,
    scores: np.ndarray,
    group_ids: Sequence[object],
    n_bootstrap: int,
    seed: int,
) -> dict[str, float | list[float] | int]:
    """AUC and interval resampled at the predeclared group, never path, level."""

    labels = np.asarray(labels)
    scores = np.asarray(scores, dtype=np.float64)
    groups = np.asarray([str(group) for group in group_ids])
    if not (labels.ndim == scores.ndim == groups.ndim == 1 and len(labels) == len(scores) == len(groups)):
        raise MechanismInvariantError("labels, scores, and group ids must be equal-length vectors")
    if n_bootstrap <= 0:
        raise MechanismInvariantError("n_bootstrap must be positive")
    unique_groups, inverse = np.unique(groups, return_inverse=True)
    group_labels = np.empty(len(unique_groups), dtype=int)
    group_indices: list[np.ndarray] = []
    for group_index in range(len(unique_groups)):
        indices = np.flatnonzero(inverse == group_index)
        unique_labels = np.unique(labels[indices])
        if len(unique_labels) != 1 or unique_labels[0] not in (0, 1):
            raise MechanismInvariantError("each bootstrap group must carry one binary record label")
        group_labels[group_index] = int(unique_labels[0])
        group_indices.append(indices)
    healthy_groups = np.flatnonzero(group_labels == 0)
    damaged_groups = np.flatnonzero(group_labels == 1)
    if not len(healthy_groups) or not len(damaged_groups):
        raise MechanismInvariantError("group bootstrap requires healthy and damaged groups")
    point_auc = float(roc_auc_score(labels, scores))
    rng = np.random.default_rng(seed)
    bootstrap = np.empty(n_bootstrap, dtype=np.float64)
    for index in range(n_bootstrap):
        selected = np.concatenate(
            (
                rng.choice(healthy_groups, size=len(healthy_groups), replace=True),
                rng.choice(damaged_groups, size=len(damaged_groups), replace=True),
            )
        )
        rows = np.concatenate([group_indices[group] for group in selected])
        bootstrap[index] = roc_auc_score(labels[rows], scores[rows])
    return {
        "roc_auc": point_auc,
        "roc_auc_ci95": [float(np.quantile(bootstrap, 0.025)), float(np.quantile(bootstrap, 0.975))],
        "healthy_group_count": int(len(healthy_groups)),
        "damaged_group_count": int(len(damaged_groups)),
        "bootstrap_unit": "predeclared_group",
    }


def paired_group_auc_difference(
    labels: np.ndarray,
    first_scores: np.ndarray,
    second_scores: np.ndarray,
    group_ids: Sequence[object],
    n_bootstrap: int,
    seed: int,
) -> dict[str, float | list[float]]:
    """Paired group-resampled AUC difference for two fixed scoring heads."""

    labels = np.asarray(labels)
    first_scores = np.asarray(first_scores, dtype=np.float64)
    second_scores = np.asarray(second_scores, dtype=np.float64)
    if first_scores.shape != second_scores.shape:
        raise MechanismInvariantError("paired score vectors must have the same shape")
    if n_bootstrap <= 0:
        raise MechanismInvariantError("n_bootstrap must be positive")
    # Run the shared structural validation before sampling, then use a single
    # seeded group sequence for both heads.
    grouped_auc_bootstrap(labels, first_scores, group_ids, 1, seed)
    groups = np.asarray([str(group) for group in group_ids])
    unique_groups, inverse = np.unique(groups, return_inverse=True)
    group_indices = [np.flatnonzero(inverse == index) for index in range(len(unique_groups))]
    group_labels = np.asarray([int(labels[indices[0]]) for indices in group_indices])
    healthy_groups = np.flatnonzero(group_labels == 0)
    damaged_groups = np.flatnonzero(group_labels == 1)
    rng = np.random.default_rng(seed)
    bootstrap = np.empty(n_bootstrap, dtype=np.float64)
    for index in range(n_bootstrap):
        selected = np.concatenate(
            (
                rng.choice(healthy_groups, size=len(healthy_groups), replace=True),
                rng.choice(damaged_groups, size=len(damaged_groups), replace=True),
            )
        )
        rows = np.concatenate([group_indices[group] for group in selected])
        bootstrap[index] = roc_auc_score(labels[rows], first_scores[rows]) - roc_auc_score(labels[rows], second_scores[rows])
    point = float(roc_auc_score(labels, first_scores) - roc_auc_score(labels, second_scores))
    return {
        "auc_difference": point,
        "auc_difference_ci95": [float(np.quantile(bootstrap, 0.025)), float(np.quantile(bootstrap, 0.975))],
        "positive_means_first_head_has_higher_auc": True,
    }
