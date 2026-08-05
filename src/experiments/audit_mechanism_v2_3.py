"""Mechanism-v2.3 entry point for read-only confirmation auditing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments import audit_mechanism_v2_2 as _impl
from src.experiments import mechanism_v2_3_successor as _successor


DEFAULT_PROTOCOL = _successor.ROOT / "protocols" / "mechanism_v2_3.json"
DEFAULT_MANIFEST = _successor.ROOT / "protocols" / "mechanism_v2_3_data_manifest.json"
DEFAULT_FREEZE_RECEIPT = _successor.ROOT / "protocols" / "mechanism_v2_3_freeze_receipt.json"


_impl.SUCCESSOR_PROTOCOL_ID = _successor.SUCCESSOR_PROTOCOL_ID
_impl.load_successor_protocol = _successor.load_successor_protocol
_impl.load_successor_manifest = _successor.load_successor_manifest
_impl.resolve_within_root = _successor.resolve_within_root
_impl.verify_successor_freeze = _successor.verify_successor_freeze


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        _impl.audit_result(args.protocol, args.manifest, args.freeze_receipt, args.result)
    except (_impl.base.AuditError, _successor.SuccessorError) as error:
        print(f"{_successor.SUCCESSOR_PROTOCOL_ID.upper()} AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    print(f"{_successor.SUCCESSOR_PROTOCOL_ID} audit passed: {args.result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
