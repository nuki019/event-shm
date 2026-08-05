"""Write the frozen, no-value MORPHO structural-discovery receipt."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.data.mechanism_hdf5_metadata_safe_v2_4 import SafeMetadataError, inspect_hdf5_structure_without_values
from src.experiments.mechanism_v2_4_metadata_discovery import (
    DiscoveryError,
    ROOT,
    load_discovery_protocol,
    resolve_within_root,
    sha256_file,
    validate_predecessor_and_input,
    verify_discovery_freeze,
)


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_4_morpho_metadata_discovery.json"
DEFAULT_FREEZE_RECEIPT = ROOT / "protocols" / "mechanism_v2_4_morpho_metadata_discovery_freeze_receipt.json"
DEFAULT_OUTPUT = ROOT / "results" / "mechanism_v2_4_morpho_metadata_discovery.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        args.output = resolve_within_root(args.output, "metadata-discovery output", must_exist=False)
        if args.output.exists():
            raise DiscoveryError(f"refusing to overwrite metadata-discovery output: {args.output}")
        protocol = verify_discovery_freeze(args.protocol, args.freeze_receipt)
        protocol_path = resolve_within_root(args.protocol, "metadata-discovery protocol")
        freeze_path = resolve_within_root(args.freeze_receipt, "metadata-discovery freeze receipt")
        invalidation_path, h5_path, history = validate_predecessor_and_input(protocol)
        observed_sha256 = sha256_file(h5_path)
        expected_sha256 = protocol["input_integrity_history"]["hdf5"]["sha256"]
        if observed_sha256 != expected_sha256:
            raise DiscoveryError("MORPHO HDF5 SHA-256 differs from the frozen metadata-discovery contract")
        inventory = inspect_hdf5_structure_without_values(h5_path)
        result = {
            "discovery_id": "mechanism-v2.4-morpho-structural-metadata-discovery-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": sha256_file(protocol_path),
            "freeze_receipt_sha256": sha256_file(freeze_path),
            "predecessor_invalidation_sha256": sha256_file(invalidation_path),
            "input": {
                "dataset_id": history["dataset_id"],
                "integrity_history_receipt": str(resolve_within_root(protocol["input_integrity_history"]["receipt_path"], "MORPHO integrity-history receipt").relative_to(ROOT)),
                "integrity_history_receipt_sha256": sha256_file(resolve_within_root(protocol["input_integrity_history"]["receipt_path"], "MORPHO integrity-history receipt")),
                "hdf5_path": str(h5_path.relative_to(ROOT)),
                "hdf5_sha256": observed_sha256,
                "hdf5_size_bytes": h5_path.stat().st_size,
            },
            "inventory": inventory,
            "access_receipt": {
                "raw_bytes_hashed_before_hdf5_open": True,
                "waveform_values_read": False,
                "metadata_values_read": False,
                "attribute_values_read": False,
                "labels_read": False,
                "signal_metrics_computed": False,
                "event_cache_written": False,
                "schema_eligibility_decided": False,
                "mapping_selected": False,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (DiscoveryError, SafeMetadataError) as error:
        print(f"MORPHO METADATA DISCOVERY FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
