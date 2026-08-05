"""Freeze the document-only MORPHO semantic-discovery contract."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.mechanism_v2_4_metadata_discovery import DiscoveryError, ROOT, resolve_within_root, sha256_file
from src.experiments.mechanism_v2_4_morpho_semantic_discovery import SEMANTIC_PROTOCOL_ID, load_semantic_protocol, validate_semantic_provenance


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_4_morpho_semantic_discovery.json"
DEFAULT_RECEIPT = ROOT / "protocols" / "mechanism_v2_4_morpho_semantic_discovery_freeze_receipt.json"
FROZEN_SOURCE_FILES = (
    "src/experiments/mechanism_v2_4_metadata_discovery.py",
    "src/experiments/mechanism_v2_4_morpho_semantic_discovery.py",
    "src/experiments/freeze_mechanism_v2_4_morpho_semantic_discovery.py",
    "src/experiments/discover_mechanism_v2_4_morpho_semantics.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        protocol, protocol_path = load_semantic_protocol(args.protocol)
        receipt_candidate = args.receipt if args.receipt.is_absolute() else ROOT / args.receipt
        args.receipt = resolve_within_root(receipt_candidate, "semantic-discovery freeze receipt", must_exist=False)
        if args.receipt.exists():
            raise DiscoveryError(f"refusing to overwrite semantic-discovery freeze receipt: {args.receipt}")
        structural_path, structural_result, document_paths = validate_semantic_provenance(protocol)
        source_hashes = {relative: sha256_file(resolve_within_root(relative, "frozen semantic-discovery source")) for relative in FROZEN_SOURCE_FILES}
        receipt = {
            "receipt_id": "mechanism-v2.4-morpho-semantic-discovery-freeze-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": SEMANTIC_PROTOCOL_ID,
            "protocol_path": str(protocol_path.relative_to(ROOT)),
            "protocol_sha256": sha256_file(protocol_path),
            "structural_result_path": str(structural_path.relative_to(ROOT)),
            "structural_result_sha256": sha256_file(structural_path),
            "structural_freeze_receipt_sha256": structural_result["freeze_receipt_sha256"],
            "document_paths": {key: str(path.relative_to(ROOT)) for key, path in document_paths.items()},
            "document_expected_sha256": {key: protocol["input_documents"][key]["sha256"] for key in document_paths},
            "frozen_source_files": list(FROZEN_SOURCE_FILES),
            "frozen_source_sha256": source_hashes,
            "document_semantics_only": True,
            "waveform_values_read_before_receipt": False,
            "hdf5_opened_by_semantic_discovery": False,
        }
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    except DiscoveryError as error:
        print(f"MORPHO SEMANTIC-DISCOVERY FREEZE FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
