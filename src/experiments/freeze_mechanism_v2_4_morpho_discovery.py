"""Freeze the no-value MORPHO structural-discovery contract before access."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.mechanism_v2_4_metadata_discovery import (
    DISCOVERY_PROTOCOL_ID,
    DiscoveryError,
    ROOT,
    load_discovery_protocol,
    resolve_within_root,
    sha256_file,
    validate_predecessor_and_input,
)


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_4_morpho_metadata_discovery.json"
DEFAULT_RECEIPT = ROOT / "protocols" / "mechanism_v2_4_morpho_metadata_discovery_freeze_receipt.json"
FROZEN_SOURCE_FILES = (
    "src/data/mechanism_hdf5_metadata_safe_v2_4.py",
    "src/experiments/mechanism_v2_4_metadata_discovery.py",
    "src/experiments/freeze_mechanism_v2_4_morpho_discovery.py",
    "src/experiments/discover_mechanism_v2_4_morpho_metadata.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        protocol, protocol_path = load_discovery_protocol(args.protocol)
        receipt_candidate = args.receipt if args.receipt.is_absolute() else ROOT / args.receipt
        args.receipt = resolve_within_root(receipt_candidate, "metadata-discovery freeze receipt", must_exist=False)
        if args.receipt.exists():
            raise DiscoveryError(f"refusing to overwrite metadata-discovery freeze receipt: {args.receipt}")
        invalidation_path, h5_path, _ = validate_predecessor_and_input(protocol)
        source_hashes = {relative: sha256_file(resolve_within_root(relative, "frozen metadata-discovery source")) for relative in FROZEN_SOURCE_FILES}
        history_path = resolve_within_root(protocol["input_integrity_history"]["receipt_path"], "MORPHO integrity-history receipt")
        receipt = {
            "receipt_id": "mechanism-v2.4-morpho-metadata-discovery-freeze-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": DISCOVERY_PROTOCOL_ID,
            "protocol_path": str(protocol_path.relative_to(ROOT)),
            "protocol_sha256": sha256_file(protocol_path),
            "predecessor_invalidation_path": str(invalidation_path.relative_to(ROOT)),
            "predecessor_invalidation_sha256": sha256_file(invalidation_path),
            "integrity_history_receipt_path": str(history_path.relative_to(ROOT)),
            "integrity_history_receipt_sha256": sha256_file(history_path),
            "hdf5_path": str(h5_path.relative_to(ROOT)),
            "hdf5_expected_sha256": protocol["input_integrity_history"]["hdf5"]["sha256"],
            "frozen_source_files": list(FROZEN_SOURCE_FILES),
            "frozen_source_sha256": source_hashes,
            "metadata_discovery_only": True,
            "waveform_values_read_before_receipt": False,
            "attribute_values_read_before_receipt": False,
        }
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    except DiscoveryError as error:
        print(f"MORPHO METADATA-DISCOVERY FREEZE FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
