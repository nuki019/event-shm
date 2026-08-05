"""Byte-accounted codecs for the strict post-compensation benchmark.

All codecs consume the same signed-16-bit residual representation.  The
quantizer is fitted only on a caller-provided training split; every packet is
serialized before its size is reported.  This deliberately separates a
shared decoder model from per-record payload, so a learned PCA basis cannot
silently become free.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from math import ceil, sqrt
from typing import Iterator, Sequence

import numpy as np


INT16_LIMIT = 32767


def encode_uvarint(value: int) -> bytes:
    """Encode a non-negative integer with base-128 varint coding."""

    if value < 0:
        raise ValueError("uvarint requires a non-negative value")
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def decode_uvarint(payload: bytes, offset: int = 0) -> tuple[int, int]:
    """Decode a base-128 varint and return ``(value, next_offset)``."""

    value = 0
    shift = 0
    while True:
        if offset >= len(payload) or shift > 63:
            raise ValueError("invalid uvarint payload")
        byte = payload[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7


def _zigzag_encode(value: int) -> int:
    return (value << 1) if value >= 0 else ((-value << 1) - 1)


def _zigzag_decode(value: int) -> int:
    return (value >> 1) if not value & 1 else -((value >> 1) + 1)


def encode_svarint(value: int) -> bytes:
    return encode_uvarint(_zigzag_encode(value))


def decode_svarint(payload: bytes, offset: int = 0) -> tuple[int, int]:
    value, offset = decode_uvarint(payload, offset)
    return _zigzag_decode(value), offset


def _round_divide_signed(values: np.ndarray, divisor: int) -> np.ndarray:
    """Round integer values to nearest level with ties away from zero."""

    if divisor <= 0:
        raise ValueError("divisor must be positive")
    values = np.asarray(values, dtype=np.int64)
    magnitude = (np.abs(values) + divisor // 2) // divisor
    return np.where(values < 0, -magnitude, magnitude)


@dataclass(frozen=True)
class Int16SignalQuantizer:
    """A shared fixed-point contract fitted from a training split only."""

    scale: float

    @classmethod
    def fit(cls, arrays: Sequence[np.ndarray]) -> "Int16SignalQuantizer":
        maximum = 0.0
        for values in arrays:
            maximum = max(maximum, float(np.max(np.abs(values))))
        if not np.isfinite(maximum) or maximum <= 0:
            raise ValueError("training residuals must contain a finite non-zero value")
        return cls(scale=maximum / INT16_LIMIT)

    @property
    def model_bytes(self) -> int:
        # IEEE-754 float64 scale; it is shared configuration, not payload.
        return 8

    def quantize(self, values: np.ndarray) -> tuple[np.ndarray, int]:
        scaled = np.rint(np.asarray(values, dtype=np.float64) / self.scale)
        saturated = int(np.count_nonzero((scaled < -INT16_LIMIT) | (scaled > INT16_LIMIT)))
        return np.clip(scaled, -INT16_LIMIT, INT16_LIMIT).astype(np.int16), saturated

    def dequantize(self, codes: np.ndarray) -> np.ndarray:
        return np.asarray(codes, dtype=np.float32) * np.float32(self.scale)


class RecordCodec:
    """Common codec interface used by the strict experiment runner."""

    name = "abstract"
    variable_path_payload = False

    @property
    def model_bytes(self) -> int:
        raise NotImplementedError

    def encode_path(self, codes: np.ndarray) -> bytes:
        raise NotImplementedError

    def decode_path(self, payload: bytes, n_samples: int) -> np.ndarray:
        raise NotImplementedError

    def reconstruction_energy(self, codes: np.ndarray) -> float:
        raise NotImplementedError

    def maximum_record_bytes(self, n_paths: int, n_samples: int) -> int | None:
        """Return an exact or conservative record-payload bound when available."""

        if self.variable_path_payload:
            return None
        return int(n_paths * len(self.encode_path(np.zeros(n_samples, dtype=np.int16))))

    def encode_record(self, record_codes: np.ndarray) -> bytes:
        """Serialize all paths, including required variable-length framing."""

        out = bytearray()
        for path_codes in np.asarray(record_codes):
            path_payload = self.encode_path(path_codes)
            if self.variable_path_payload:
                out.extend(encode_uvarint(len(path_payload)))
            out.extend(path_payload)
        return bytes(out)

    def decode_record(self, payload: bytes, n_paths: int, n_samples: int) -> np.ndarray:
        if self.variable_path_payload:
            decoded = []
            offset = 0
            for _ in range(n_paths):
                size, offset = decode_uvarint(payload, offset)
                stop = offset + size
                if stop > len(payload):
                    raise ValueError("truncated variable-length record packet")
                decoded.append(self.decode_path(payload[offset:stop], n_samples))
                offset = stop
            if offset != len(payload):
                raise ValueError("trailing bytes in record packet")
            return np.stack(decoded)

        path_size = len(self.encode_path(np.zeros(n_samples, dtype=np.int16)))
        if len(payload) != n_paths * path_size:
            raise ValueError("invalid fixed-length record packet")
        return np.stack(
            [self.decode_path(payload[p * path_size:(p + 1) * path_size], n_samples) for p in range(n_paths)]
        )

    def evaluate_record(self, record_codes: np.ndarray) -> tuple[float, int]:
        """Return reconstructed energy and exact serialized packet byte count."""

        record_codes = np.asarray(record_codes)
        energy = float(sum(self.reconstruction_energy(path_codes) for path_codes in record_codes))
        return energy / max(len(record_codes), 1), len(self.encode_record(record_codes))


@dataclass(frozen=True)
class SodPathTrace:
    """Auditable event stream facts for one SoD path packet.

    ``candidate_*`` describes every level crossing before a packet limit is
    applied, while ``transmitted_*`` describes the serialized event stream.
    This distinction makes quantization collision and cap-induced terminal
    hold observable without changing the packet format.
    """

    payload: bytes
    quantized_levels: np.ndarray
    candidate_event_indices: np.ndarray
    candidate_event_level_deltas: np.ndarray
    transmitted_event_indices: np.ndarray
    transmitted_event_level_deltas: np.ndarray
    transmitted_levels: np.ndarray
    last_transmitted_event_index: int | None
    packet_cap_bytes: int | None
    cap_saturated: bool
    terminal_hold_samples: int
    cap_hold_samples: int

    @property
    def packet_bytes(self) -> int:
        return len(self.payload)

    @property
    def packet_utilization(self) -> float | None:
        if self.packet_cap_bytes is None:
            return None
        return float(self.packet_bytes / self.packet_cap_bytes)

    @property
    def event_count(self) -> int:
        """Count transmitted level changes, excluding the initial level."""

        return int(len(self.transmitted_event_indices))

    @property
    def candidate_event_count(self) -> int:
        """Count all pre-cap level changes, excluding the initial level."""

        return int(len(self.candidate_event_indices))


@dataclass(frozen=True)
class SodRecordTrace:
    """Serialized record packet and the corresponding per-path traces."""

    payload: bytes
    path_traces: tuple[SodPathTrace, ...]

    @property
    def packet_bytes(self) -> int:
        return len(self.payload)

    @property
    def cap_saturated_path_count(self) -> int:
        return sum(trace.cap_saturated for trace in self.path_traces)


@dataclass(frozen=True)
class SodTransitionCodec(RecordCodec):
    """Streaming SoD packet with timestamp gaps and signed level changes."""

    delta_codes: int
    signal_scale: float
    max_path_payload_bytes: int | None = None
    name: str = "sod_transition_bounded"
    variable_path_payload: bool = True

    def __post_init__(self) -> None:
        if self.delta_codes <= 0:
            raise ValueError("delta_codes must be positive")
        if self.max_path_payload_bytes is not None:
            minimum = len(encode_svarint(INT16_LIMIT))
            if self.max_path_payload_bytes < minimum:
                raise ValueError(f"max_path_payload_bytes must be at least {minimum}")

    @property
    def model_bytes(self) -> int:
        return 8 + 2 + (4 if self.max_path_payload_bytes is not None else 0)

    def _levels(self, codes: np.ndarray) -> np.ndarray:
        return _round_divide_signed(np.asarray(codes, dtype=np.int16), self.delta_codes)

    def trace_path(self, codes: np.ndarray) -> SodPathTrace:
        """Serialize one path and expose every event/cap decision.

        A configured cap stops at an event boundary.  The normal SoD decoder
        then holds the final transmitted level for the remaining samples, so
        the truncated packet is still self-contained and decodable.
        """

        levels = self._levels(codes)
        if levels.size == 0:
            empty = np.empty(0, dtype=np.int64)
            return SodPathTrace(
                payload=b"",
                quantized_levels=empty,
                candidate_event_indices=empty,
                candidate_event_level_deltas=empty,
                transmitted_event_indices=empty,
                transmitted_event_level_deltas=empty,
                transmitted_levels=empty,
                last_transmitted_event_index=None,
                packet_cap_bytes=self.max_path_payload_bytes,
                cap_saturated=False,
                terminal_hold_samples=0,
                cap_hold_samples=0,
            )
        changes = np.flatnonzero(np.diff(levels) != 0) + 1
        candidate_deltas = levels[changes] - levels[changes - 1]
        out = bytearray(encode_svarint(int(levels[0])))
        starts = [0]
        transmitted_levels = [int(levels[0])]
        transmitted_indices: list[int] = []
        transmitted_deltas: list[int] = []
        previous_index = 0
        previous_level = int(levels[0])
        cap_saturated = False
        for index in changes:
            current = int(levels[index])
            level_delta = current - previous_level
            event = encode_uvarint(int(index) - previous_index) + encode_svarint(level_delta)
            if self.max_path_payload_bytes is not None and len(out) + len(event) > self.max_path_payload_bytes:
                cap_saturated = True
                break
            out.extend(event)
            starts.append(int(index))
            transmitted_levels.append(current)
            transmitted_indices.append(int(index))
            transmitted_deltas.append(level_delta)
            previous_index = int(index)
            previous_level = current
        last_index = int(starts[-1])
        terminal_hold = int(len(levels) - last_index)
        return SodPathTrace(
            payload=bytes(out),
            quantized_levels=levels,
            candidate_event_indices=changes.astype(np.int64, copy=False),
            candidate_event_level_deltas=candidate_deltas.astype(np.int64, copy=False),
            transmitted_event_indices=np.asarray(transmitted_indices, dtype=np.int64),
            transmitted_event_level_deltas=np.asarray(transmitted_deltas, dtype=np.int64),
            transmitted_levels=np.asarray(transmitted_levels, dtype=np.int64),
            last_transmitted_event_index=last_index,
            packet_cap_bytes=self.max_path_payload_bytes,
            cap_saturated=cap_saturated,
            terminal_hold_samples=terminal_hold,
            cap_hold_samples=terminal_hold if cap_saturated else 0,
        )

    def trace_record(self, record_codes: np.ndarray) -> SodRecordTrace:
        """Return per-path audit traces whose payload exactly matches encoding."""

        record_codes = np.asarray(record_codes, dtype=np.int16)
        if record_codes.ndim != 2:
            raise ValueError("record_codes must have shape (paths, samples)")
        traces = tuple(self.trace_path(path_codes) for path_codes in record_codes)
        packet = bytearray()
        for trace in traces:
            packet.extend(encode_uvarint(trace.packet_bytes))
            packet.extend(trace.payload)
        return SodRecordTrace(payload=bytes(packet), path_traces=traces)

    def _serialize_path(self, codes: np.ndarray) -> tuple[bytes, np.ndarray, np.ndarray]:
        """Compatibility helper used by the frozen E7 implementation."""

        trace = self.trace_path(codes)
        starts = np.concatenate((np.array([0], dtype=np.int64), trace.transmitted_event_indices)) if trace.transmitted_levels.size else np.empty(0, dtype=np.int64)
        return trace.payload, starts, trace.transmitted_levels

    def encode_path(self, codes: np.ndarray) -> bytes:
        return self.trace_path(codes).payload

    def decode_path(self, payload: bytes, n_samples: int) -> np.ndarray:
        if n_samples < 0:
            raise ValueError("n_samples must be non-negative")
        if n_samples == 0:
            if payload:
                raise ValueError("empty signal has non-empty payload")
            return np.empty(0, dtype=np.int16)
        if not payload:
            raise ValueError("non-empty signal has empty SoD payload")
        level, offset = decode_svarint(payload)
        output = np.empty(n_samples, dtype=np.int64)
        previous_index = 0
        while offset < len(payload):
            delta_index, offset = decode_uvarint(payload, offset)
            level_delta, offset = decode_svarint(payload, offset)
            index = previous_index + delta_index
            if index <= previous_index or index >= n_samples:
                raise ValueError("invalid SoD event timestamp")
            output[previous_index:index] = level * self.delta_codes
            level += level_delta
            previous_index = index
        output[previous_index:] = level * self.delta_codes
        return np.clip(output, -INT16_LIMIT, INT16_LIMIT).astype(np.int16)

    def reconstruction_energy(self, codes: np.ndarray) -> float:
        _, starts, levels = self._serialize_path(codes)
        if not len(levels):
            return 0.0
        ends = np.concatenate((starts[1:], [len(codes)]))
        reconstructed_codes = np.clip(levels * self.delta_codes, -INT16_LIMIT, INT16_LIMIT).astype(np.float64)
        values = reconstructed_codes * self.signal_scale
        lengths = (ends - starts).astype(np.float64)
        return float(np.dot(lengths, values * values))

    def maximum_record_bytes(self, n_paths: int, n_samples: int) -> int | None:
        if self.max_path_payload_bytes is None:
            return None
        header_bytes = len(encode_uvarint(self.max_path_payload_bytes))
        return int(n_paths * (self.max_path_payload_bytes + header_bytes))

    def evaluate_record_metrics(self, record_codes: np.ndarray) -> tuple[float, int, float]:
        """Return energy, packet bytes, and code-domain MSE from one packet pass."""

        record_codes = np.asarray(record_codes, dtype=np.int16)
        if record_codes.ndim != 2:
            raise ValueError("record_codes must have shape (paths, samples)")
        total_energy = 0.0
        total_error = 0.0
        total_samples = 0
        packet = bytearray()
        for path_codes in record_codes:
            payload, starts, levels = self._serialize_path(path_codes)
            packet.extend(encode_uvarint(len(payload)))
            packet.extend(payload)
            if not len(levels):
                continue
            ends = np.concatenate((starts[1:], [len(path_codes)]))
            lengths = (ends - starts).astype(np.float64)
            reconstructed_codes = np.clip(levels * self.delta_codes, -INT16_LIMIT, INT16_LIMIT).astype(np.float64)
            amplitudes = reconstructed_codes * self.signal_scale
            total_energy += float(np.dot(lengths, amplitudes * amplitudes))

            source = path_codes.astype(np.float64)
            cumulative = np.empty(len(source) + 1, dtype=np.float64)
            cumulative[0] = 0.0
            np.cumsum(source, out=cumulative[1:])
            cumulative_squared = np.empty(len(source) + 1, dtype=np.float64)
            cumulative_squared[0] = 0.0
            np.cumsum(source * source, out=cumulative_squared[1:])
            segment_sum = cumulative[ends] - cumulative[starts]
            segment_squared = cumulative_squared[ends] - cumulative_squared[starts]
            total_error += float(np.sum(segment_squared - 2.0 * reconstructed_codes * segment_sum + lengths * reconstructed_codes**2))
            total_samples += len(source)
        return (
            total_energy / max(len(record_codes), 1),
            len(packet),
            total_error / max(total_samples, 1),
        )

    def evaluate_record(self, record_codes: np.ndarray) -> tuple[float, int]:
        energy, payload, _ = self.evaluate_record_metrics(record_codes)
        return energy, payload


@dataclass(frozen=True)
class UniformLinearCodec(RecordCodec):
    """Fixed-grid signed-int16 samples reconstructed by linear interpolation."""

    stride: int
    signal_scale: float
    name: str = "uniform_linear"
    variable_path_payload: bool = False

    def __post_init__(self) -> None:
        if self.stride <= 0:
            raise ValueError("stride must be positive")

    @property
    def model_bytes(self) -> int:
        return 8 + 4

    def _indices(self, n_samples: int) -> np.ndarray:
        if n_samples <= 0:
            return np.empty(0, dtype=np.int64)
        indices = np.arange(0, n_samples, self.stride, dtype=np.int64)
        if indices[-1] != n_samples - 1:
            indices = np.concatenate((indices, [n_samples - 1]))
        return indices

    def encode_path(self, codes: np.ndarray) -> bytes:
        codes = np.asarray(codes, dtype=np.int16)
        return codes[self._indices(len(codes))].astype("<i2", copy=False).tobytes()

    def decode_path(self, payload: bytes, n_samples: int) -> np.ndarray:
        indices = self._indices(n_samples)
        expected = 2 * len(indices)
        if len(payload) != expected:
            raise ValueError("invalid uniform packet length")
        if not n_samples:
            return np.empty(0, dtype=np.float32)
        values = np.frombuffer(payload, dtype="<i2").astype(np.float64)
        decoded = np.interp(np.arange(n_samples), indices, values)
        return decoded.astype(np.float32)

    def reconstruction_energy(self, codes: np.ndarray) -> float:
        codes = np.asarray(codes, dtype=np.int16)
        indices = self._indices(len(codes))
        if not len(indices):
            return 0.0
        values = codes[indices].astype(np.float64) * self.signal_scale
        if len(indices) == 1:
            return float(values[0] * values[0])
        lengths = np.diff(indices).astype(np.float64)
        a = values[:-1]
        d = values[1:] - a
        sum_t = lengths * (lengths - 1.0) / 2.0
        sum_t2 = lengths * (lengths - 1.0) * (2.0 * lengths - 1.0) / 6.0
        segment_energy = lengths * a * a
        segment_energy += 2.0 * a * d * (sum_t / lengths)
        segment_energy += d * d * (sum_t2 / (lengths * lengths))
        return float(segment_energy.sum() + values[-1] * values[-1])


def _iter_rows(codes: np.ndarray, signal_scale: float, batch_rows: int) -> Iterator[np.ndarray]:
    """Yield float32 path waveforms without materializing the full matrix."""

    codes = np.asarray(codes)
    if codes.ndim != 3:
        raise ValueError("expected record array shaped (records, paths, samples)")
    records, paths, samples = codes.shape
    for record_start in range(0, records, max(1, ceil(batch_rows / paths))):
        record_stop = min(records, record_start + max(1, ceil(batch_rows / paths)))
        rows = codes[record_start:record_stop].reshape(-1, samples)
        for row_start in range(0, len(rows), batch_rows):
            yield rows[row_start:row_start + batch_rows].astype(np.float32) * np.float32(signal_scale)


@dataclass(frozen=True)
class PcaModel:
    """Shared PCA decoder model fit exclusively from training residuals."""

    mean: np.ndarray
    components: np.ndarray
    coefficient_scales: np.ndarray
    signal_scale: float

    @property
    def max_rank(self) -> int:
        return int(self.components.shape[0])

    @classmethod
    def fit(
        cls,
        training_codes: np.ndarray,
        signal_scale: float,
        max_rank: int = 128,
        batch_rows: int = 264,
        random_state: int = 20260729,
    ) -> "PcaModel":
        """Fit incremental PCA and coefficient quantizers from training only."""

        from sklearn.decomposition import IncrementalPCA

        rows = int(training_codes.shape[0] * training_codes.shape[1])
        if rows < max_rank:
            raise ValueError("training split has fewer path waveforms than max_rank")
        pca = IncrementalPCA(n_components=max_rank, batch_size=batch_rows)
        # IncrementalPCA is deterministic; retain the argument to make the
        # caller's seed contract explicit and future implementation changes visible.
        _ = random_state
        for batch in _iter_rows(training_codes, signal_scale, batch_rows):
            if len(batch) >= max_rank:
                pca.partial_fit(batch)

        maximum = np.zeros(max_rank, dtype=np.float64)
        for batch in _iter_rows(training_codes, signal_scale, batch_rows):
            coefficients = pca.transform(batch)
            maximum = np.maximum(maximum, np.max(np.abs(coefficients), axis=0))
        coefficient_scales = maximum / INT16_LIMIT
        coefficient_scales[coefficient_scales <= 0] = 1.0
        return cls(
            mean=np.asarray(pca.mean_, dtype=np.float32),
            components=np.asarray(pca.components_, dtype=np.float32),
            coefficient_scales=np.asarray(coefficient_scales, dtype=np.float32),
            signal_scale=float(signal_scale),
        )

    def evaluate_records(
        self,
        record_codes: np.ndarray,
        ranks: Sequence[int],
        batch_records: int = 4,
    ) -> dict[int, tuple[np.ndarray, np.ndarray]]:
        """Evaluate several rank prefixes with one coefficient projection.

        All requested ranks share the frozen decoder basis.  Projecting the
        largest prefix once per batch avoids refitting or re-reading a record
        for each storage target while preserving the same rank-specific
        coefficient quantization used by :class:`PcaCodec`.
        """

        record_codes = np.asarray(record_codes)
        if record_codes.ndim != 3:
            raise ValueError("record_codes must have shape (records, paths, samples)")
        requested = tuple(sorted(set(int(rank) for rank in ranks)))
        if not requested or requested[0] <= 0 or requested[-1] > self.max_rank:
            raise ValueError("requested ranks must be non-empty and within the fitted PCA model")
        if record_codes.shape[2] != len(self.mean):
            raise ValueError("record sample length differs from decoder model")
        if batch_records <= 0:
            raise ValueError("batch_records must be positive")

        records, paths, samples = record_codes.shape
        scores = {rank: np.empty(records, dtype=np.float64) for rank in requested}
        payloads = {rank: np.full(records, paths * rank * 2, dtype=np.int64) for rank in requested}
        maximum_rank = requested[-1]
        components = self.components[:maximum_rank]
        scales = self.coefficient_scales[:maximum_rank]
        mean = self.mean
        mean64 = mean.astype(np.float64)
        components64 = components.astype(np.float64)
        mean_energy = float(np.dot(mean64, mean64))
        projection = components64 @ mean64

        for start in range(0, records, batch_records):
            stop = min(records, start + batch_records)
            signal = np.asarray(record_codes[start:stop], dtype=np.float32) * np.float32(self.signal_scale)
            rows = signal.reshape(-1, samples)
            coefficients = (rows - mean) @ components.T
            quantized = np.rint(coefficients / scales)
            quantized = np.clip(quantized, -INT16_LIMIT, INT16_LIMIT).astype(np.int16)
            decoded = quantized.astype(np.float64) * scales.astype(np.float64)
            component_energy = 2.0 * decoded * projection + decoded * decoded
            prefix_energy = np.cumsum(component_energy, axis=1)
            for rank in requested:
                path_energy = mean_energy + prefix_energy[:, rank - 1]
                scores[rank][start:stop] = path_energy.reshape(stop - start, paths).mean(axis=1)

        return {rank: (scores[rank], payloads[rank]) for rank in requested}


@dataclass(frozen=True)
class PcaCodec(RecordCodec):
    """PCA coefficients quantized to signed int16 with explicit model size."""

    model: PcaModel
    rank: int
    name: str = "pca"
    variable_path_payload: bool = False

    def __post_init__(self) -> None:
        if not 0 < self.rank <= self.model.max_rank:
            raise ValueError("rank must be within the fitted PCA model")

    @property
    def model_bytes(self) -> int:
        return int(
            self.model.mean.nbytes
            + self.model.components[:self.rank].nbytes
            + self.model.coefficient_scales[:self.rank].nbytes
            + 8
        )

    def _quantized_coefficients(self, codes: np.ndarray) -> np.ndarray:
        signal = np.asarray(codes, dtype=np.float32) * np.float32(self.model.signal_scale)
        coefficients = self.model.components[:self.rank] @ (signal - self.model.mean)
        quantized = np.rint(coefficients / self.model.coefficient_scales[:self.rank])
        return np.clip(quantized, -INT16_LIMIT, INT16_LIMIT).astype(np.int16)

    @cached_property
    def _energy_terms(self) -> tuple[float, np.ndarray]:
        components = self.model.components[:self.rank].astype(np.float64)
        mean = self.model.mean.astype(np.float64)
        return float(np.dot(mean, mean)), components @ mean

    def encode_path(self, codes: np.ndarray) -> bytes:
        return self._quantized_coefficients(codes).astype("<i2", copy=False).tobytes()

    def _coefficients_from_payload(self, payload: bytes) -> np.ndarray:
        if len(payload) != self.rank * 2:
            raise ValueError("invalid PCA packet length")
        quantized = np.frombuffer(payload, dtype="<i2").astype(np.float32)
        return quantized * self.model.coefficient_scales[:self.rank]

    def decode_path(self, payload: bytes, n_samples: int) -> np.ndarray:
        if n_samples != len(self.model.mean):
            raise ValueError("PCA packet sample length differs from decoder model")
        coefficients = self._coefficients_from_payload(payload)
        signal = self.model.mean + coefficients @ self.model.components[:self.rank]
        return (signal / self.model.signal_scale).astype(np.float32)

    def reconstruction_energy(self, codes: np.ndarray) -> float:
        coefficients = self._quantized_coefficients(codes).astype(np.float64)
        coefficients *= self.model.coefficient_scales[:self.rank].astype(np.float64)
        mean_energy, projection = self._energy_terms
        return float(mean_energy + 2.0 * np.dot(coefficients, projection) + np.dot(coefficients, coefficients))

    def evaluate_record(self, record_codes: np.ndarray) -> tuple[float, int]:
        """Vectorize all path coefficients for a record-sized packet."""

        signal = np.asarray(record_codes, dtype=np.float32) * np.float32(self.model.signal_scale)
        coefficients = (signal - self.model.mean) @ self.model.components[:self.rank].T
        quantized = np.rint(coefficients / self.model.coefficient_scales[:self.rank])
        quantized = np.clip(quantized, -INT16_LIMIT, INT16_LIMIT).astype(np.int16)
        decoded_coefficients = quantized.astype(np.float64) * self.model.coefficient_scales[:self.rank]
        mean_energy, projection = self._energy_terms
        energies = mean_energy + 2.0 * (decoded_coefficients @ projection) + np.sum(decoded_coefficients * decoded_coefficients, axis=1)
        return float(np.mean(energies)), int(quantized.nbytes)


def next_power_of_two(value: int) -> int:
    if value <= 0:
        raise ValueError("value must be positive")
    return 1 << (value - 1).bit_length()


def haar_forward(values: np.ndarray, padded_length: int | None = None) -> np.ndarray:
    """Return an orthonormal Haar transform, zero-padding at the signal tail."""

    values = np.asarray(values, dtype=np.float32)
    padded_length = padded_length or next_power_of_two(len(values))
    if padded_length < len(values) or padded_length & (padded_length - 1):
        raise ValueError("padded_length must be a power of two at least as large as the signal")
    work = np.zeros(padded_length, dtype=np.float32)
    work[:len(values)] = values
    temp = np.empty_like(work)
    width = padded_length
    inv_sqrt_two = np.float32(1.0 / sqrt(2.0))
    while width > 1:
        even = work[:width:2]
        odd = work[1:width:2]
        half = width // 2
        temp[:half] = (even + odd) * inv_sqrt_two
        temp[half:width] = (even - odd) * inv_sqrt_two
        work[:width] = temp[:width]
        width = half
    return work


def haar_inverse(coefficients: np.ndarray) -> np.ndarray:
    """Invert :func:`haar_forward` for a power-of-two coefficient vector."""

    work = np.asarray(coefficients, dtype=np.float32).copy()
    if len(work) == 0 or len(work) & (len(work) - 1):
        raise ValueError("Haar coefficient vector length must be a non-zero power of two")
    temp = np.empty_like(work)
    width = 1
    inv_sqrt_two = np.float32(1.0 / sqrt(2.0))
    while width < len(work):
        averages = work[:width]
        details = work[width:2 * width]
        temp[:2 * width:2] = (averages + details) * inv_sqrt_two
        temp[1:2 * width:2] = (averages - details) * inv_sqrt_two
        work[:2 * width] = temp[:2 * width]
        width *= 2
    return work


def fit_haar_scale(training_codes: np.ndarray, signal_scale: float, batch_rows: int = 256) -> float:
    """Fit one fixed signed-int16 coefficient scale from training only."""

    maximum = 0.0
    for batch in _iter_rows(training_codes, signal_scale, batch_rows):
        for row in batch:
            maximum = max(maximum, float(np.max(np.abs(haar_forward(row)))))
    if not np.isfinite(maximum) or maximum <= 0:
        raise ValueError("training data cannot fit a Haar coefficient scale")
    return maximum / INT16_LIMIT


@dataclass(frozen=True)
class HaarDwtCodec(RecordCodec):
    """Sparse Haar packet with varint coefficient positions and int16 values."""

    top_k: int
    coefficient_scale: float
    signal_scale: float
    padded_length: int
    name: str = "haar_dwt"
    variable_path_payload: bool = True

    def __post_init__(self) -> None:
        if self.top_k <= 0 or self.top_k > self.padded_length:
            raise ValueError("top_k must be within the padded Haar length")
        if self.coefficient_scale <= 0:
            raise ValueError("coefficient_scale must be positive")

    @property
    def model_bytes(self) -> int:
        return 8 + 4 + 4

    def _selected(self, codes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        coefficients = haar_forward(np.asarray(codes, dtype=np.float32) * np.float32(self.signal_scale), self.padded_length)
        magnitudes = np.abs(coefficients)
        provisional = np.argpartition(magnitudes, -self.top_k)[-self.top_k:]
        cutoff = float(np.min(magnitudes[provisional]))
        strictly_larger = np.flatnonzero(magnitudes > cutoff)
        tied = np.flatnonzero(magnitudes == cutoff)
        selected = np.concatenate((strictly_larger, tied[:self.top_k - len(strictly_larger)]))
        selected.sort()
        values = np.rint(coefficients[selected] / self.coefficient_scale)
        return selected.astype(np.int64), np.clip(values, -INT16_LIMIT, INT16_LIMIT).astype(np.int16)

    def encode_path(self, codes: np.ndarray) -> bytes:
        indices, values = self._selected(codes)
        out = bytearray()
        previous = 0
        for index in indices:
            out.extend(encode_uvarint(int(index) - previous))
            previous = int(index)
        out.extend(values.astype("<i2", copy=False).tobytes())
        return bytes(out)

    def _parse(self, payload: bytes) -> tuple[np.ndarray, np.ndarray]:
        indices = np.empty(self.top_k, dtype=np.int64)
        offset = 0
        previous = 0
        for position in range(self.top_k):
            delta, offset = decode_uvarint(payload, offset)
            index = previous + delta
            if (position and index <= previous) or index < previous or index >= self.padded_length:
                raise ValueError("invalid Haar coefficient index")
            indices[position] = index
            previous = index
        expected = offset + self.top_k * 2
        if len(payload) != expected:
            raise ValueError("invalid Haar packet length")
        values = np.frombuffer(payload[offset:], dtype="<i2").astype(np.float32)
        return indices, values

    def decode_path(self, payload: bytes, n_samples: int) -> np.ndarray:
        if n_samples > self.padded_length:
            raise ValueError("signal exceeds Haar padded length")
        indices, values = self._parse(payload)
        coefficients = np.zeros(self.padded_length, dtype=np.float32)
        coefficients[indices] = values * np.float32(self.coefficient_scale)
        signal = haar_inverse(coefficients)[:n_samples]
        return (signal / self.signal_scale).astype(np.float32)

    def reconstruction_energy(self, codes: np.ndarray) -> float:
        _, values = self._selected(codes)
        reconstructed_coefficients = values.astype(np.float64) * self.coefficient_scale
        return float(np.dot(reconstructed_coefficients, reconstructed_coefficients))

    def maximum_record_bytes(self, n_paths: int, n_samples: int) -> int | None:
        maximum_position_bytes = len(encode_uvarint(self.padded_length - 1))
        maximum_path_payload = self.top_k * (maximum_position_bytes + 2)
        header_bytes = len(encode_uvarint(maximum_path_payload))
        return int(n_paths * (maximum_path_payload + header_bytes))
