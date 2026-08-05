"""Pure in-memory canonical result contract for mechanism-v2.7.

This module is intentionally limited to synthetic, pre-access result
envelopes.  It does not open files, resolve paths, import data libraries, or
perform network operations.  In particular, it cannot inspect or authorize
real waveform data.  A later frozen protocol may bind this contract, but this
module is not itself a protocol, freeze receipt, or data-access mechanism.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any


CONTRACT_ID = "mechanism-v2.7-canonical-result-contract-v1"
PROTOCOL_ID = "mechanism-v2.7"
RESULT_KIND = "synthetic_preaccess_contract_validation"
SYNTHETIC_ONLY_MODE = "synthetic_only"

CAPACITIES = (2048, 4096, 8192, 16384)
DELTAS = (1, 8, 64, 512, 4096, 8192, 16384, 32767)
EXPECTED_GRID_PAIRS = tuple((capacity, delta) for capacity in CAPACITIES for delta in DELTAS)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")

_TOP_LEVEL_FIELDS = frozenset(
    {
        "contract_id",
        "protocol_id",
        "result_kind",
        "run_id",
        "authorization_not_before_utc",
        "started_utc",
        "completed_utc",
        "data_access",
        "synthetic_input",
        "grid",
        "grid_sha256",
        "envelope_sha256",
    }
)
_DATA_ACCESS_FIELDS = frozenset(
    {
        "mode",
        "real_waveform_accessed",
        "external_data_accessed",
        "contacted_dataset_ids",
        "previously_contacted_dataset_ids",
        "contacted_artifact_ids",
        "first_real_waveform_access_utc",
    }
)
_SYNTHETIC_INPUT_FIELDS = frozenset({"generator_id", "seed", "input_sha256"})
_CELL_FIELDS = frozenset(
    {
        "capacity_bytes",
        "delta_codes",
        "status",
        "payload_bytes_per_record",
        "event_count",
        "cap_saturated",
        "synthetic_trace_sha256",
    }
)


class MechanismV27ContractError(ValueError):
    """Raised when a result cannot be a canonical v2.7 synthetic envelope."""


def canonical_json_bytes(payload: Any) -> bytes:
    """Return the unique JSON representation used by all contract hashes."""

    try:
        return json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise MechanismV27ContractError(f"payload is not canonical JSON: {error}") from error


def canonical_sha256(payload: Any) -> str:
    """Hash an in-memory JSON payload without any filesystem or data access."""

    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def grid_sha256(grid: Any) -> str:
    """Return the canonical hash of the complete synthetic grid payload."""

    return canonical_sha256(grid)


def envelope_sha256(envelope: dict[str, Any]) -> str:
    """Return the envelope hash, excluding its self-referential hash field."""

    if not isinstance(envelope, dict):
        raise MechanismV27ContractError("result envelope must be a JSON object")
    return canonical_sha256({key: value for key, value in envelope.items() if key != "envelope_sha256"})


def seal_result_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Return a copied envelope with canonical grid and envelope hashes.

    Sealing deliberately does not make malformed data valid.  Call
    :func:`validate_result_envelope` before accepting the result.
    """

    if not isinstance(envelope, dict):
        raise MechanismV27ContractError("result envelope must be a JSON object")
    if "grid" not in envelope:
        raise MechanismV27ContractError("result envelope lacks grid")
    try:
        sealed = json.loads(canonical_json_bytes(envelope).decode("utf-8"))
    except json.JSONDecodeError as error:  # Defensive: canonical JSON is emitted above.
        raise MechanismV27ContractError(f"cannot copy result envelope: {error}") from error
    sealed["grid_sha256"] = grid_sha256(sealed["grid"])
    sealed["envelope_sha256"] = envelope_sha256(sealed)
    return sealed


def validate_result_envelope(
    envelope: dict[str, Any],
    *,
    not_before_utc: str | None = None,
    data_contacted_utc: str | None = None,
) -> dict[str, Any]:
    """Validate and return a copied canonical synthetic result envelope.

    ``not_before_utc`` is an optional caller-supplied authorization boundary.
    ``data_contacted_utc`` is an optional known first real-data contact time.
    A result completed at or after that contact is rejected, which keeps this
    contract usable for pre-access validation receipts without reading a
    contact ledger or any data source itself.
    """

    if not isinstance(envelope, dict):
        raise MechanismV27ContractError("result envelope must be a JSON object")
    try:
        checked = json.loads(canonical_json_bytes(envelope).decode("utf-8"))
    except json.JSONDecodeError as error:  # Defensive: canonical JSON is emitted above.
        raise MechanismV27ContractError(f"cannot copy result envelope: {error}") from error

    _require_exact_keys(checked, _TOP_LEVEL_FIELDS, "result envelope")
    _require_equal(checked, "contract_id", CONTRACT_ID)
    _require_equal(checked, "protocol_id", PROTOCOL_ID)
    _require_equal(checked, "result_kind", RESULT_KIND)

    run_id = checked["run_id"]
    if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
        raise MechanismV27ContractError("run_id must be a stable lowercase identifier, not a path")

    authorization = _parse_utc(checked["authorization_not_before_utc"], "authorization_not_before_utc")
    started = _parse_utc(checked["started_utc"], "started_utc")
    completed = _parse_utc(checked["completed_utc"], "completed_utc")
    if started < authorization:
        raise MechanismV27ContractError("started_utc precedes authorization_not_before_utc")
    if completed < started:
        raise MechanismV27ContractError("completed_utc precedes started_utc")
    if not_before_utc is not None:
        requested_boundary = _parse_utc(not_before_utc, "not_before_utc")
        if authorization < requested_boundary or started < requested_boundary:
            raise MechanismV27ContractError("result precedes the caller-supplied not_before_utc boundary")
    if data_contacted_utc is not None:
        first_contact = _parse_utc(data_contacted_utc, "data_contacted_utc")
        if completed >= first_contact:
            raise MechanismV27ContractError("result is not pre-contact with respect to data_contacted_utc")

    _validate_data_access(checked["data_access"])
    _validate_synthetic_input(checked["synthetic_input"])
    _validate_grid(checked["grid"])

    _require_sha256(checked["grid_sha256"], "grid_sha256")
    if checked["grid_sha256"] != grid_sha256(checked["grid"]):
        raise MechanismV27ContractError("grid_sha256 does not match the canonical grid")
    _require_sha256(checked["envelope_sha256"], "envelope_sha256")
    if checked["envelope_sha256"] != envelope_sha256(checked):
        raise MechanismV27ContractError("envelope_sha256 does not match the canonical result envelope")
    return checked


def _require_exact_keys(value: Any, required: frozenset[str], label: str) -> None:
    if not isinstance(value, dict):
        raise MechanismV27ContractError(f"{label} must be a JSON object")
    actual = frozenset(value)
    missing = sorted(required - actual)
    extra = sorted(actual - required)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise MechanismV27ContractError(f"{label} fields are invalid: {'; '.join(details)}")


def _require_equal(value: dict[str, Any], field: str, expected: str) -> None:
    if value[field] != expected:
        raise MechanismV27ContractError(f"{field} must equal {expected!r}")


def _require_sha256(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise MechanismV27ContractError(f"{label} must be a lowercase SHA-256 hex digest")


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not _UTC_RE.fullmatch(value):
        raise MechanismV27ContractError(f"{label} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as error:
        raise MechanismV27ContractError(f"{label} is not a valid UTC timestamp") from error


def _validate_data_access(access: Any) -> None:
    _require_exact_keys(access, _DATA_ACCESS_FIELDS, "data_access")
    if access["mode"] != SYNTHETIC_ONLY_MODE:
        raise MechanismV27ContractError("data_access.mode must be synthetic_only")
    for field in ("real_waveform_accessed", "external_data_accessed"):
        if access[field] is not False:
            raise MechanismV27ContractError(f"synthetic-only result forbids {field}")
    for field in ("contacted_dataset_ids", "previously_contacted_dataset_ids", "contacted_artifact_ids"):
        if not isinstance(access[field], list) or access[field]:
            raise MechanismV27ContractError(f"synthetic-only result forbids {field}")
    if access["first_real_waveform_access_utc"] is not None:
        raise MechanismV27ContractError("synthetic-only result forbids first_real_waveform_access_utc")


def _validate_synthetic_input(synthetic_input: Any) -> None:
    _require_exact_keys(synthetic_input, _SYNTHETIC_INPUT_FIELDS, "synthetic_input")
    generator_id = synthetic_input["generator_id"]
    if not isinstance(generator_id, str) or not _RUN_ID_RE.fullmatch(generator_id):
        raise MechanismV27ContractError("synthetic_input.generator_id must be a stable lowercase identifier")
    seed = synthetic_input["seed"]
    if type(seed) is not int or seed < 0:
        raise MechanismV27ContractError("synthetic_input.seed must be a non-negative integer")
    _require_sha256(synthetic_input["input_sha256"], "synthetic_input.input_sha256")


def _validate_grid(grid: Any) -> None:
    if not isinstance(grid, list):
        raise MechanismV27ContractError("grid must be a JSON array")
    if len(grid) != len(EXPECTED_GRID_PAIRS):
        raise MechanismV27ContractError(f"grid must contain all {len(EXPECTED_GRID_PAIRS)} fixed cells")
    pairs: list[tuple[int, int]] = []
    for index, cell in enumerate(grid):
        _require_exact_keys(cell, _CELL_FIELDS, f"grid[{index}]")
        capacity = cell["capacity_bytes"]
        delta = cell["delta_codes"]
        if type(capacity) is not int or capacity not in CAPACITIES:
            raise MechanismV27ContractError(f"grid[{index}].capacity_bytes is outside the fixed grid")
        if type(delta) is not int or delta not in DELTAS:
            raise MechanismV27ContractError(f"grid[{index}].delta_codes is outside the fixed grid")
        pairs.append((capacity, delta))
        if cell["status"] != "synthetic_scored":
            raise MechanismV27ContractError(f"grid[{index}].status must be synthetic_scored")
        payload_bytes = cell["payload_bytes_per_record"]
        if type(payload_bytes) not in (int, float) or not math.isfinite(float(payload_bytes)) or payload_bytes < 0:
            raise MechanismV27ContractError(f"grid[{index}].payload_bytes_per_record must be finite and non-negative")
        event_count = cell["event_count"]
        if type(event_count) is not int or event_count < 0:
            raise MechanismV27ContractError(f"grid[{index}].event_count must be a non-negative integer")
        if type(cell["cap_saturated"]) is not bool:
            raise MechanismV27ContractError(f"grid[{index}].cap_saturated must be boolean")
        _require_sha256(cell["synthetic_trace_sha256"], f"grid[{index}].synthetic_trace_sha256")
    if tuple(pairs) != EXPECTED_GRID_PAIRS:
        raise MechanismV27ContractError("grid must contain each fixed (capacity_bytes, delta_codes) cell once in canonical order")
