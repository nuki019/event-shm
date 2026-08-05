"""Mechanism-v2.3 entry point for one-shot OGW confirmation.

This wrapper deliberately owns argument defaults instead of borrowing the
v2.2 parser.  That keeps the v2.3 cache and result namespaces disjoint even
when callers use no explicit path arguments.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments import e9_mechanism_v2_2_ogw as _impl
from src.experiments import mechanism_v2_3_successor as _successor


DEFAULT_PROTOCOL = _successor.ROOT / "protocols" / "mechanism_v2_3.json"
DEFAULT_MANIFEST = _successor.ROOT / "protocols" / "mechanism_v2_3_data_manifest.json"
DEFAULT_FREEZE_RECEIPT = _successor.ROOT / "protocols" / "mechanism_v2_3_freeze_receipt.json"
DEFAULT_OUTPUTS = {
    "D12": _successor.ROOT / "results" / "mechanism_v2_3_ogw_d12_confirmation.json",
    "D16": _successor.ROOT / "results" / "mechanism_v2_3_ogw_d16_confirmation.json",
}


# The validated v2.2 runner contains the one-shot execution logic.  Bind its
# process-local collaborators to v2.3 before calling ``run``; no v2.2 file is
# edited or written by this wrapper.
_impl.SUCCESSOR_PROTOCOL_ID = _successor.SUCCESSOR_PROTOCOL_ID
_impl.load_successor_protocol = _successor.load_successor_protocol
_impl.load_successor_manifest = _successor.load_successor_manifest
_impl.resolve_within_root = _successor.resolve_within_root
_impl.verify_successor_freeze = _successor.verify_successor_freeze


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", choices=("D12", "D16"), required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument(
        "--calibration-receipt",
        type=Path,
        default=_successor.ROOT / "results" / "mechanism_v2_ogw_udam_source_receipt.json",
    )
    parser.add_argument("--confirmation-receipt", type=Path, required=True)
    parser.add_argument("--strict-cache-dir", type=Path, default=_successor.ROOT / "data" / "interim" / "strict_codec_v1")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--force-cache", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    condition = args.condition.upper()
    if args.cache_dir is None:
        args.cache_dir = _successor.ROOT / "data" / "interim" / f"mechanism_v2_3_ogw_{condition.lower()}"
    if args.output is None:
        args.output = DEFAULT_OUTPUTS[condition]
    return args


def main() -> int:
    try:
        _impl.run(parse_args())
    except (_impl.base.ConfirmationError, _successor.SuccessorError) as error:
        print(f"{_successor.SUCCESSOR_PROTOCOL_ID.upper()} OGW CONFIRMATION FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
