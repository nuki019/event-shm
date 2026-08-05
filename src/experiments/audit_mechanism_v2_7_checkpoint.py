"""Read-only auditor for synthetic mechanism-v2.7 checkpoint ledgers.

This module deliberately rechecks the ledger wire format instead of acquiring
a writer lease or calling a runner.  It cannot create, update, resume, or
release an attempt, and it has no data-source or waveform interface.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

# Preserve the documented ``python src/experiments/...py`` entry point as well
# as module execution.  This only locates repository code; it never opens a
# dataset or a checkpoint ledger by itself.
if __package__ in {None, ""}:
    workspace_root = str(Path(__file__).resolve().parents[2])
    if workspace_root not in sys.path:
        sys.path.insert(0, workspace_root)

from src.experiments.mechanism_v2_7_checkpoint import (
    AttemptBinding,
    CheckpointHeadExpectation,
    CheckpointLedgerError,
    HeadAnchorAuthority,
    _validate_gate_document,
    checkpoint_audit_guard,
    verify_head_anchor,
)


LEDGER_FORMAT = "mechanism-v2.7-checkpoint-ledger-v1"
ACTIVE_STATE = "active"
TERMINAL_STATES = frozenset({"completed", "invalidated", "aborted"})
GENESIS_PREVIOUS_SHA256 = "0" * 64
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_UTC_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")
_BINDING_FIELDS = ("freeze_sha256", "source_sha256", "code_sha256")
_DOCUMENT_FIELDS = {
    "format",
    "attempt_id",
    "binding",
    "binding_sha256",
    "metadata",
    "state",
    "entries",
    "ledger_sha256",
}


class MechanismV27CheckpointAuditError(ValueError):
    """Raised when a ledger is not a complete, internally consistent audit object."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MechanismV27CheckpointAuditError(message)


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise MechanismV27CheckpointAuditError(f"ledger is not canonical JSON: {error}") from error


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _without_field(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    return {key: copy.deepcopy(item) for key, item in value.items() if key != field_name}


def _require_digest(name: str, value: Any) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise MechanismV27CheckpointAuditError(
            f"{name} must be a lowercase 64-character SHA-256 hex digest"
        )
    return value


def _parse_utc_timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        raise MechanismV27CheckpointAuditError(
            f"{field_name} must be an ISO-8601 UTC timestamp ending in Z"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MechanismV27CheckpointAuditError(f"{field_name} is not a valid timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise MechanismV27CheckpointAuditError(f"{field_name} must be UTC")
    return parsed


def _audit_binding(binding: Any, expected_binding: Mapping[str, str]) -> tuple[dict[str, str], str]:
    if not isinstance(binding, dict) or set(binding) != set(_BINDING_FIELDS):
        raise MechanismV27CheckpointAuditError("binding must contain exactly freeze/source/code hashes")
    normalized = {field_name: _require_digest(field_name, binding[field_name]) for field_name in _BINDING_FIELDS}
    if set(expected_binding) != set(_BINDING_FIELDS) or dict(expected_binding) != normalized:
        raise MechanismV27CheckpointAuditError("ledger binding differs from the auditor's expected identity")
    return normalized, _sha256(normalized)


def _audit_entry(
    entry: Any,
    *,
    sequence: int,
    previous_entry_sha256: str,
    attempt_id: str,
    binding_sha256: str,
) -> tuple[str, str | None, datetime, str | None]:
    if not isinstance(entry, dict):
        raise MechanismV27CheckpointAuditError(f"entry {sequence} must be an object")
    event = entry.get("event")
    expected_fields = {
        "sequence",
        "event",
        "attempt_id",
        "recorded_at_utc",
        "previous_entry_sha256",
        "binding_sha256",
        "payload",
        "entry_sha256",
    }
    if event == "checkpoint":
        expected_fields.add("checkpoint_id")
    elif event == "terminal":
        expected_fields.add("terminal_state")
    elif event != "attempt_started":
        raise MechanismV27CheckpointAuditError(f"entry {sequence} has an unknown event")
    if set(entry) != expected_fields:
        raise MechanismV27CheckpointAuditError(f"entry {sequence} has an invalid field set")
    if not isinstance(entry.get("sequence"), int) or isinstance(entry["sequence"], bool) or entry["sequence"] != sequence:
        raise MechanismV27CheckpointAuditError(f"entry {sequence} has an invalid sequence")
    if sequence == 0 and event != "attempt_started":
        raise MechanismV27CheckpointAuditError("first entry must be attempt_started")
    if sequence > 0 and event == "attempt_started":
        raise MechanismV27CheckpointAuditError("attempt_started may appear only once")
    if entry.get("previous_entry_sha256") != previous_entry_sha256:
        raise MechanismV27CheckpointAuditError(f"entry {sequence} breaks the hash chain")
    _require_digest(f"entry {sequence} previous_entry_sha256", entry["previous_entry_sha256"])
    if entry.get("attempt_id") != attempt_id:
        raise MechanismV27CheckpointAuditError(f"entry {sequence} is bound to another attempt")
    if entry.get("binding_sha256") != binding_sha256:
        raise MechanismV27CheckpointAuditError(f"entry {sequence} is bound to another freeze/source/code identity")
    _require_digest(f"entry {sequence} binding_sha256", entry["binding_sha256"])
    recorded_at = _parse_utc_timestamp(entry.get("recorded_at_utc"), f"entry {sequence} recorded_at_utc")
    if not isinstance(entry.get("payload"), dict):
        raise MechanismV27CheckpointAuditError(f"entry {sequence} payload must be an object")
    checkpoint_id: str | None = None
    if event == "checkpoint":
        checkpoint_id = entry.get("checkpoint_id")
        if not isinstance(checkpoint_id, str) or not checkpoint_id:
            raise MechanismV27CheckpointAuditError(f"entry {sequence} has an invalid checkpoint_id")
    terminal_state: str | None = None
    if event == "terminal":
        terminal_state = entry.get("terminal_state")
        if terminal_state not in TERMINAL_STATES:
            raise MechanismV27CheckpointAuditError(f"entry {sequence} has an invalid terminal_state")
    _require_digest(f"entry {sequence} entry_sha256", entry.get("entry_sha256"))
    if entry["entry_sha256"] != _sha256(_without_field(entry, "entry_sha256")):
        raise MechanismV27CheckpointAuditError(f"entry {sequence} hash does not match its content")
    return entry["entry_sha256"], terminal_state, recorded_at, checkpoint_id


def audit_checkpoint_payload(
    payload: Mapping[str, Any],
    *,
    expectation: CheckpointHeadExpectation,
    anchor_authority: HeadAnchorAuthority,
) -> dict[str, Any]:
    """Audit a terminal parsed ledger against an independently retained head."""

    if not isinstance(expectation, CheckpointHeadExpectation):
        raise MechanismV27CheckpointAuditError("a CheckpointHeadExpectation is required")

    if not isinstance(payload, Mapping) or set(payload) != _DOCUMENT_FIELDS:
        raise MechanismV27CheckpointAuditError("ledger has an invalid top-level field set")
    if payload.get("format") != LEDGER_FORMAT:
        raise MechanismV27CheckpointAuditError("ledger format is not mechanism-v2.7-checkpoint-ledger-v1")
    attempt_id = payload.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise MechanismV27CheckpointAuditError("ledger lacks a non-empty attempt_id")
    if attempt_id != expectation.attempt_id:
        raise MechanismV27CheckpointAuditError("ledger attempt_id differs from the auditor's expected head")
    binding, binding_sha256 = _audit_binding(payload.get("binding"), expectation.binding.as_dict())
    if payload.get("binding_sha256") != binding_sha256:
        raise MechanismV27CheckpointAuditError("binding_sha256 does not match the binding")
    _require_digest("binding_sha256", payload["binding_sha256"])
    if not isinstance(payload.get("metadata"), dict):
        raise MechanismV27CheckpointAuditError("ledger metadata must be an object")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise MechanismV27CheckpointAuditError("ledger must contain a start entry")
    _require_digest("ledger_sha256", payload.get("ledger_sha256"))
    if payload["ledger_sha256"] != _sha256(_without_field(payload, "ledger_sha256")):
        raise MechanismV27CheckpointAuditError("ledger_sha256 does not match the document")
    if payload["ledger_sha256"] != expectation.ledger_sha256:
        raise MechanismV27CheckpointAuditError("ledger_sha256 differs from the auditor's expected head")
    try:
        verify_head_anchor(anchor_authority, expectation)
    except CheckpointLedgerError as error:
        raise MechanismV27CheckpointAuditError(str(error)) from error

    previous_hash = GENESIS_PREVIOUS_SHA256
    previous_time: datetime | None = None
    checkpoint_ids: set[str] = set()
    terminal_states: list[str] = []
    for sequence, entry in enumerate(entries):
        entry_hash, terminal_state, recorded_at, checkpoint_id = _audit_entry(
            entry,
            sequence=sequence,
            previous_entry_sha256=previous_hash,
            attempt_id=attempt_id,
            binding_sha256=binding_sha256,
        )
        if previous_time is not None and recorded_at <= previous_time:
            raise MechanismV27CheckpointAuditError("ledger timestamps must be strictly increasing UTC instants")
        if checkpoint_id is not None:
            if checkpoint_id in checkpoint_ids:
                raise MechanismV27CheckpointAuditError(f"checkpoint_id is repeated: {checkpoint_id}")
            checkpoint_ids.add(checkpoint_id)
        if terminal_state is not None:
            terminal_states.append(terminal_state)
            if sequence != len(entries) - 1:
                raise MechanismV27CheckpointAuditError("terminal entry must be final")
        previous_hash = entry_hash
        previous_time = recorded_at

    state = payload.get("state")
    if state not in TERMINAL_STATES or terminal_states != [state]:
        raise MechanismV27CheckpointAuditError("only a terminal ledger may receive a final checkpoint audit")
    return {
        "format": payload["format"],
        "attempt_id": attempt_id,
        "binding": binding,
        "binding_sha256": binding_sha256,
        "metadata": copy.deepcopy(payload["metadata"]),
        "state": state,
        "entries": copy.deepcopy(entries),
        "ledger_sha256": payload["ledger_sha256"],
    }


def _read_stable_snapshot(path: Path) -> bytes:
    """Read one ledger snapshot and reject path replacement during the read."""

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError as error:
        raise MechanismV27CheckpointAuditError(f"cannot open checkpoint ledger: {error}") from error
    try:
        before = os.fstat(descriptor)
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining > 0:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        path_stat = path.stat()
    except OSError as error:
        raise MechanismV27CheckpointAuditError(f"cannot read checkpoint ledger: {error}") from error
    finally:
        os.close(descriptor)
    identity_before = before.st_dev, before.st_ino
    identity_after = after.st_dev, after.st_ino
    path_identity = path_stat.st_dev, path_stat.st_ino
    if len(payload) != before.st_size or identity_before != identity_after or identity_before != path_identity:
        raise MechanismV27CheckpointAuditError("checkpoint ledger changed while its audit snapshot was read")
    return payload


def audit_checkpoint_file(
    ledger_path: str | Path,
    *,
    expectation: CheckpointHeadExpectation,
    anchor_authority: HeadAnchorAuthority,
) -> dict[str, Any]:
    """Audit one terminal ledger while a shared OS guard excludes writers."""

    path = Path(ledger_path)
    lock_path = path.with_name(f".{path.name}.writer.lock")
    try:
        with checkpoint_audit_guard(path) as gate:
            gate.assert_held()
            if lock_path.exists():
                raise MechanismV27CheckpointAuditError(
                    "writer lease sidecar exists; a concurrent or stale attempt cannot be audited"
                )
            raw_before = _read_stable_snapshot(path)
            try:
                payload = json.loads(raw_before.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise MechanismV27CheckpointAuditError(f"cannot parse checkpoint ledger: {error}") from error
            _validate_gate_document(gate, payload)
            audited = audit_checkpoint_payload(
                payload,
                expectation=expectation,
                anchor_authority=anchor_authority,
            )
            raw_after = _read_stable_snapshot(path)
            if raw_after != raw_before or lock_path.exists():
                raise MechanismV27CheckpointAuditError(
                    "checkpoint ledger or writer state changed during final audit"
                )
            gate.assert_held()
            return audited
    except CheckpointLedgerError as error:
        raise MechanismV27CheckpointAuditError(str(error)) from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True, help="synthetic checkpoint ledger JSON")
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--code-sha256", required=True)
    parser.add_argument("--expected-ledger-sha256", required=True)
    parser.add_argument("--anchor-id", required=True)
    parser.add_argument("--anchor-sha256", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    # A real pass must inject a verifier tied to an append-only remote anchor.
    # This repository intentionally has no such adapter before a qualified
    # source, source-specific freeze, and protected publication target exist.
    try:
        expectation = CheckpointHeadExpectation(
            attempt_id=args.attempt_id,
            binding=AttemptBinding(
                freeze_sha256=args.freeze_sha256,
                source_sha256=args.source_sha256,
                code_sha256=args.code_sha256,
            ),
            ledger_sha256=args.expected_ledger_sha256,
            anchor_id=args.anchor_id,
            anchor_sha256=args.anchor_sha256,
        )
    except (CheckpointLedgerError, TypeError) as error:
        print(f"MECHANISM-V2.7 CHECKPOINT AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    del expectation
    print(
        "MECHANISM-V2.7 CHECKPOINT AUDIT REFUSED: no production HeadAnchorAuthority is configured; "
        "a local ledger must not be promoted to a final audit receipt.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
