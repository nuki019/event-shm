"""Synthetic terminal-hold pre-access evidence for mechanism-v2.7.

This module deliberately accepts only scalar grid parameters.  It never takes
a waveform path, opens a dataset, or creates an experiment protocol.  Each
cell builds two synthetic integer-code trajectories which are identical through
the first event rejected by the per-path cap and deliberately diverge only
after that event.  A passing cell therefore proves the codec's terminal-hold
contract for the requested capacity allocation without accessing real data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.methods.strict_codecs import INT16_LIMIT, SodPathTrace, SodTransitionCodec, encode_svarint, encode_uvarint


RUNNER_ID = "mechanism-v2.7-terminal-hold-preaccess-v1"
RUNNER_PATH = Path(__file__).resolve()
CODEC_PATH = ROOT / "src" / "methods" / "strict_codecs.py"


@dataclass(frozen=True)
class CellResult:
    """JSON-safe, per-grid-cell terminal-hold evidence."""

    capacity_bytes: int
    delta_codes: int
    n_paths: int
    n_samples: int
    per_path_cap_bytes: int | None
    applicable: bool
    status: str
    reason: str | None
    first_blocked_event_index: int | None
    first_cap_saturated: bool | None
    second_cap_saturated: bool | None
    first_has_terminal_hold: bool | None
    second_has_terminal_hold: bool | None
    same_serialized_payload: bool | None
    same_payload_sha256: bool | None
    same_decoded_output: bool | None
    same_decoded_sha256: bool | None
    input_trajectories_differ: bool | None
    first_trace: dict[str, Any] | None
    second_trace: dict[str, Any] | None


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _array_sha256(values: np.ndarray) -> str:
    """Hash an integer-code trajectory with an explicit portable dtype."""

    return _sha256_bytes(np.asarray(values, dtype="<i2").tobytes())


def _utc_now() -> str:
    """Return the actual current UTC timestamp, rather than a frozen literal."""

    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _source_hashes() -> dict[str, str]:
    """Bind output to the runner and codec source actually executed."""

    return {
        "runner_sha256": _sha256_bytes(RUNNER_PATH.read_bytes()),
        "strict_codecs_sha256": _sha256_bytes(CODEC_PATH.read_bytes()),
    }


def _path_cap(total_capacity_bytes: int, n_paths: int) -> int:
    """Allocate a common decodable path cap within a whole-record budget."""

    for candidate in range(total_capacity_bytes // n_paths, 0, -1):
        if n_paths * (candidate + len(encode_uvarint(candidate))) <= total_capacity_bytes:
            return candidate
    raise ValueError("total capacity cannot allocate a positive encoded path payload")


def _normalise_positive_ints(name: str, values: Sequence[int]) -> list[int]:
    """Validate ordered integer grid input without silently coercing values."""

    normalised: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise TypeError(f"{name} must contain integers")
        integer = int(value)
        if integer <= 0:
            raise ValueError(f"{name} must contain positive integers")
        normalised.append(integer)
    if not normalised:
        raise ValueError(f"{name} must be non-empty")
    if len(set(normalised)) != len(normalised):
        raise ValueError(f"{name} must not contain duplicate values")
    return normalised


def _synthetic_dense_trajectory(n_samples: int, delta_codes: int) -> np.ndarray:
    """Create the densest valid level-crossing trajectory for one codec path."""

    trajectory = np.zeros(n_samples, dtype=np.int16)
    trajectory[1::2] = np.int16(delta_codes)
    return trajectory


def _trace_receipt(trace: SodPathTrace, source_codes: np.ndarray, decoded_codes: np.ndarray) -> dict[str, Any]:
    """Capture enough immutable facts to audit a trace without retaining payload bytes."""

    return {
        "source_codes_sha256": _array_sha256(source_codes),
        "payload_sha256": _sha256_bytes(trace.payload),
        "decoded_codes_sha256": _array_sha256(decoded_codes),
        "payload_bytes": int(trace.packet_bytes),
        "packet_cap_bytes": None if trace.packet_cap_bytes is None else int(trace.packet_cap_bytes),
        "candidate_event_count": int(trace.candidate_event_count),
        "transmitted_event_count": int(len(trace.transmitted_event_indices)),
        "last_transmitted_event_index": None if trace.last_transmitted_event_index is None else int(trace.last_transmitted_event_index),
        "cap_saturated": bool(trace.cap_saturated),
        "terminal_hold_samples": int(trace.terminal_hold_samples),
        "cap_hold_samples": int(trace.cap_hold_samples),
    }


def _not_applicable(
    *,
    capacity_bytes: int,
    delta_codes: int,
    n_paths: int,
    n_samples: int,
    per_path_cap_bytes: int | None,
    reason: str,
    first_trace: dict[str, Any] | None = None,
) -> CellResult:
    return CellResult(
        capacity_bytes=capacity_bytes,
        delta_codes=delta_codes,
        n_paths=n_paths,
        n_samples=n_samples,
        per_path_cap_bytes=per_path_cap_bytes,
        applicable=False,
        status="not_applicable",
        reason=reason,
        first_blocked_event_index=None,
        first_cap_saturated=None if first_trace is None else bool(first_trace["cap_saturated"]),
        second_cap_saturated=None,
        first_has_terminal_hold=None if first_trace is None else bool(first_trace["cap_hold_samples"] > 0),
        second_has_terminal_hold=None,
        same_serialized_payload=None,
        same_payload_sha256=None,
        same_decoded_output=None,
        same_decoded_sha256=None,
        input_trajectories_differ=None,
        first_trace=first_trace,
        second_trace=None,
    )


def _evaluate_cell(*, n_paths: int, n_samples: int, capacity_bytes: int, delta_codes: int) -> CellResult:
    """Audit one capacity/delta cell with two synthetic post-cap trajectories."""

    try:
        per_path_cap_bytes = _path_cap(capacity_bytes, n_paths)
    except ValueError as error:
        return _not_applicable(
            capacity_bytes=capacity_bytes,
            delta_codes=delta_codes,
            n_paths=n_paths,
            n_samples=n_samples,
            per_path_cap_bytes=None,
            reason=f"capacity_allocation_unavailable: {error}",
        )

    codec_minimum = len(encode_svarint(INT16_LIMIT))
    if per_path_cap_bytes < codec_minimum:
        return _not_applicable(
            capacity_bytes=capacity_bytes,
            delta_codes=delta_codes,
            n_paths=n_paths,
            n_samples=n_samples,
            per_path_cap_bytes=per_path_cap_bytes,
            reason=(
                "per_path_cap_below_codec_minimum: "
                f"{per_path_cap_bytes} < {codec_minimum}"
            ),
        )

    if delta_codes > INT16_LIMIT:
        return _not_applicable(
            capacity_bytes=capacity_bytes,
            delta_codes=delta_codes,
            n_paths=n_paths,
            n_samples=n_samples,
            per_path_cap_bytes=per_path_cap_bytes,
            reason=(
                "delta_outside_int16_dynamic_range: "
                f"delta_codes={delta_codes} exceeds {INT16_LIMIT}"
            ),
        )

    first_codes = _synthetic_dense_trajectory(n_samples, delta_codes)
    codec = SodTransitionCodec(
        delta_codes=delta_codes,
        signal_scale=1.0,
        max_path_payload_bytes=per_path_cap_bytes,
    )
    first_trace_raw = codec.trace_path(first_codes)
    first_decoded = codec.decode_path(first_trace_raw.payload, n_samples)
    first_receipt = _trace_receipt(first_trace_raw, first_codes, first_decoded)

    if not first_trace_raw.cap_saturated:
        return _not_applicable(
            capacity_bytes=capacity_bytes,
            delta_codes=delta_codes,
            n_paths=n_paths,
            n_samples=n_samples,
            per_path_cap_bytes=per_path_cap_bytes,
            reason="n_samples_insufficient_to_saturate_per_path_cap",
            first_trace=first_receipt,
        )

    last_transmitted = first_trace_raw.last_transmitted_event_index
    blocked_candidates = [
        int(index)
        for index in first_trace_raw.candidate_event_indices
        if last_transmitted is not None and int(index) > int(last_transmitted)
    ]
    if not blocked_candidates:
        return _not_applicable(
            capacity_bytes=capacity_bytes,
            delta_codes=delta_codes,
            n_paths=n_paths,
            n_samples=n_samples,
            per_path_cap_bytes=per_path_cap_bytes,
            reason="no_post_cap_candidate_event_available",
            first_trace=first_receipt,
        )

    blocked_event_index = blocked_candidates[0]
    suffix_start = blocked_event_index + 1
    if suffix_start >= n_samples:
        return _not_applicable(
            capacity_bytes=capacity_bytes,
            delta_codes=delta_codes,
            n_paths=n_paths,
            n_samples=n_samples,
            per_path_cap_bytes=per_path_cap_bytes,
            reason="no_sample_exists_after_first_blocked_event",
            first_trace=first_receipt,
        )

    second_codes = first_codes.copy()
    replacement = 0 if first_codes[suffix_start] != 0 else delta_codes
    second_codes[suffix_start:] = np.int16(replacement)
    second_trace_raw = codec.trace_path(second_codes)
    second_decoded = codec.decode_path(second_trace_raw.payload, n_samples)
    second_receipt = _trace_receipt(second_trace_raw, second_codes, second_decoded)

    checks = {
        "first_cap_saturated": bool(first_trace_raw.cap_saturated),
        "second_cap_saturated": bool(second_trace_raw.cap_saturated),
        "first_has_terminal_hold": bool(first_trace_raw.cap_hold_samples > 0),
        "second_has_terminal_hold": bool(second_trace_raw.cap_hold_samples > 0),
        "same_serialized_payload": first_trace_raw.payload == second_trace_raw.payload,
        "same_payload_sha256": first_receipt["payload_sha256"] == second_receipt["payload_sha256"],
        "same_decoded_output": bool(np.array_equal(first_decoded, second_decoded)),
        "same_decoded_sha256": first_receipt["decoded_codes_sha256"] == second_receipt["decoded_codes_sha256"],
        "input_trajectories_differ": bool(not np.array_equal(first_codes, second_codes)),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return CellResult(
        capacity_bytes=capacity_bytes,
        delta_codes=delta_codes,
        n_paths=n_paths,
        n_samples=n_samples,
        per_path_cap_bytes=per_path_cap_bytes,
        applicable=True,
        status="passed" if not failed_checks else "failed",
        reason=None if not failed_checks else "failed_checks: " + ", ".join(failed_checks),
        first_blocked_event_index=blocked_event_index,
        first_cap_saturated=checks["first_cap_saturated"],
        second_cap_saturated=checks["second_cap_saturated"],
        first_has_terminal_hold=checks["first_has_terminal_hold"],
        second_has_terminal_hold=checks["second_has_terminal_hold"],
        same_serialized_payload=checks["same_serialized_payload"],
        same_payload_sha256=checks["same_payload_sha256"],
        same_decoded_output=checks["same_decoded_output"],
        same_decoded_sha256=checks["same_decoded_sha256"],
        input_trajectories_differ=checks["input_trajectories_differ"],
        first_trace=first_receipt,
        second_trace=second_receipt,
    )


def run_terminal_hold_preaccess_test(
    *,
    n_paths: int,
    n_samples: int,
    capacities: Sequence[int],
    deltas: Sequence[int],
) -> dict[str, Any]:
    """Run the parameterized, synthetic-only v2.7 terminal-hold grid.

    ``passed`` means no applicable cell contradicted the contract.
    ``preaccess_ready`` is stricter: every requested cell must pass, so a
    documented not-applicable cell cannot silently authorize waveform access.
    """

    if isinstance(n_paths, bool) or not isinstance(n_paths, (int, np.integer)) or int(n_paths) <= 0:
        raise ValueError("n_paths must be a positive integer")
    if isinstance(n_samples, bool) or not isinstance(n_samples, (int, np.integer)) or int(n_samples) <= 0:
        raise ValueError("n_samples must be a positive integer")
    n_paths = int(n_paths)
    n_samples = int(n_samples)
    capacity_grid = _normalise_positive_ints("capacities", capacities)
    delta_grid = _normalise_positive_ints("deltas", deltas)

    cells = [
        _evaluate_cell(
            n_paths=n_paths,
            n_samples=n_samples,
            capacity_bytes=capacity_bytes,
            delta_codes=delta_codes,
        )
        for capacity_bytes in capacity_grid
        for delta_codes in delta_grid
    ]
    cell_dicts = [asdict(cell) for cell in cells]
    passed_cells = [cell for cell in cells if cell.status == "passed"]
    not_applicable_cells = [cell for cell in cells if cell.status == "not_applicable"]
    failed_cells = [cell for cell in cells if cell.status == "failed"]

    return {
        "runner_id": RUNNER_ID,
        "generated_at_utc": _utc_now(),
        "code_hashes": _source_hashes(),
        "data_access": {
            "mode": "synthetic_only",
            "real_waveform_accessed": False,
            "real_waveform_paths": [],
            "synthetic_input_construction": "alternating integer-code levels with a post-cap divergent suffix",
        },
        "inputs": {
            "n_paths": n_paths,
            "n_samples": n_samples,
            "capacities_bytes": capacity_grid,
            "delta_codes": delta_grid,
        },
        "grid_coverage": {
            "expected_cells": len(capacity_grid) * len(delta_grid),
            "observed_cells": len(cells),
            "passed_cells": len(passed_cells),
            "not_applicable_cells": len(not_applicable_cells),
            "failed_cells": len(failed_cells),
        },
        "passed": not failed_cells,
        "preaccess_ready": len(passed_cells) == len(cells),
        "cells": cell_dicts,
    }


def write_audit_result(result: dict[str, Any], output_path: Path) -> None:
    """Persist a caller-selected audit receipt; no default results path is used."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-paths", type=int, required=True)
    parser.add_argument("--n-samples", type=int, required=True)
    parser.add_argument("--capacities", type=int, nargs="+", required=True, metavar="BYTES")
    parser.add_argument("--deltas", type=int, nargs="+", required=True, metavar="CODES")
    parser.add_argument("--output", type=Path, help="Optional caller-selected JSON receipt path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_terminal_hold_preaccess_test(
        n_paths=args.n_paths,
        n_samples=args.n_samples,
        capacities=args.capacities,
        deltas=args.deltas,
    )
    if args.output is None:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        write_audit_result(result, args.output)
        print(f"wrote audit receipt: {args.output}")
    return 0 if result["preaccess_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
