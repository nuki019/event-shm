"""Read-only auditor for synthetic mechanism-v2.7 pre-access envelopes.

This is deliberately not a runner, protocol, freeze receipt, or real-data
auditor.  It only accepts the synthetic-only canonical envelope supplied by
mechanism_v2_7_contract, so invoking it cannot authorize or interpret a
waveform result.  A later successor must freeze and extend this auditor before
any new data access.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from src.experiments.mechanism_v2_7_contract import (
    MechanismV27ContractError,
    validate_result_envelope,
)


ROOT = Path(__file__).resolve().parents[2]


class MechanismV27AuditError(ValueError):
    """Raised when a synthetic pre-access envelope is not auditable."""


def audit_synthetic_envelope(
    payload: dict[str, Any],
    *,
    not_before_utc: str | None = None,
    data_contacted_utc: str | None = None,
) -> dict[str, Any]:
    """Return a validated copy of a synthetic-only pre-access envelope.

    The contract rejects all real/external/previously contacted data.  The
    optional time boundaries are caller supplied and therefore make a later
    protocol's authorization boundary explicit rather than implicit.
    """

    try:
        return validate_result_envelope(
            payload,
            not_before_utc=not_before_utc,
            data_contacted_utc=data_contacted_utc,
        )
    except MechanismV27ContractError as error:
        raise MechanismV27AuditError(str(error)) from error


def _resolve_within_root(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise MechanismV27AuditError(f"cannot resolve result path: {path}") from error
    try:
        resolved.relative_to(ROOT)
    except ValueError as error:
        raise MechanismV27AuditError("synthetic result must remain inside the repository") from error
    if resolved.suffix.lower() != ".json":
        raise MechanismV27AuditError("synthetic result must be a JSON file")
    return resolved


def audit_synthetic_file(
    result_path: Path,
    *,
    not_before_utc: str | None = None,
    data_contacted_utc: str | None = None,
) -> dict[str, Any]:
    """Read and audit one synthetic envelope without writing any artifact."""

    resolved = _resolve_within_root(result_path)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MechanismV27AuditError(f"cannot read canonical synthetic JSON: {error}") from error
    return audit_synthetic_envelope(
        payload,
        not_before_utc=not_before_utc,
        data_contacted_utc=data_contacted_utc,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True, help="synthetic-only canonical envelope JSON")
    parser.add_argument("--not-before-utc", help="optional explicit authorization boundary")
    parser.add_argument("--data-contacted-utc", help="optional first real-data contact boundary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        checked = audit_synthetic_file(
            args.result,
            not_before_utc=args.not_before_utc,
            data_contacted_utc=args.data_contacted_utc,
        )
    except MechanismV27AuditError as error:
        print(f"MECHANISM-V2.7 SYNTHETIC PREACCESS AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "mechanism-v2.7 synthetic preaccess audit passed: "
        f"run_id={checked['run_id']} grid_sha256={checked['grid_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
