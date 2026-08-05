"""Create the immutable pre-access freeze receipt for mechanism-v2.4."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.mechanism_v2_4_successor import (
    ROOT,
    V24Error,
    external_mapping,
    json_hash,
    load_v24_manifest,
    load_v24_protocol,
    resolve_within_root,
    sha256_file,
)


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_4.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_4_data_manifest.json"
DEFAULT_RECEIPT = ROOT / "protocols" / "mechanism_v2_4_freeze_receipt.json"
FROZEN_SOURCE_FILES = (
    "src/data/mechanism_hdf5_metadata_safe_v2_4.py",
    "src/data/mechanism_v2_4_external_schema.py",
    "src/data/ogw_loader.py",
    "src/methods/strict_codecs.py",
    "src/methods/mechanism_v2.py",
    "src/experiments/e7_strict_codec_benchmark.py",
    "src/experiments/e9_mechanism_v2_ogw.py",
    "src/experiments/audit_mechanism_v2.py",
    "src/experiments/mechanism_v2_4_successor.py",
    "src/experiments/verify_mechanism_v2_4_source.py",
    "src/experiments/audit_mechanism_v2_4_external_schema.py",
    "src/experiments/bind_mechanism_v2_4_calibration.py",
    "src/experiments/e9_mechanism_v2_4_ogw.py",
    "src/experiments/audit_mechanism_v2_4.py",
    "src/experiments/audit_mechanism_v2_4_preflight.py",
    "src/experiments/freeze_mechanism_v2_4.py",
)
PREACCESS_RESULT_NAMES = (
    "mechanism_v2_4_ogw_d12_source_receipt.json",
    "mechanism_v2_4_ogw_d16_source_receipt.json",
    "mechanism_v2_4_morpho_source_receipt.json",
    "mechanism_v2_4_coqtel_source_receipt.json",
    "mechanism_v2_4_ogw_udam_calibration_binding.json",
    "mechanism_v2_4_morpho_schema_gate.json",
    "mechanism_v2_4_coqtel_schema_gate.json",
    "mechanism_v2_4_preexperiment_audit.json",
    "mechanism_v2_4_ogw_d12_confirmation.json",
    "mechanism_v2_4_ogw_d16_confirmation.json",
)


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _ensure_preaccess_state() -> None:
    occupied = [name for name in PREACCESS_RESULT_NAMES if (ROOT / "results" / name).exists()]
    if occupied:
        raise V24Error(f"v2.4 pre-access freeze must precede these receipts/results: {occupied}")
    cache_paths = [ROOT / "data" / "interim" / "mechanism_v2_4_ogw_d12", ROOT / "data" / "interim" / "mechanism_v2_4_ogw_d16"]
    occupied_caches = [str(path.relative_to(ROOT)) for path in cache_paths if path.exists()]
    if occupied_caches:
        raise V24Error(f"v2.4 pre-access freeze must precede cache creation: {occupied_caches}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        args.protocol = resolve_within_root(args.protocol, "mechanism-v2.4 protocol")
        args.manifest = resolve_within_root(args.manifest, "mechanism-v2.4 data manifest")
        receipt_candidate = args.receipt if args.receipt.is_absolute() else ROOT / args.receipt
        args.receipt = resolve_within_root(receipt_candidate, "mechanism-v2.4 freeze receipt", must_exist=False)
        if args.receipt.exists():
            raise V24Error(f"refusing to overwrite mechanism-v2.4 freeze receipt: {args.receipt}")
        protocol, _ = load_v24_protocol(args.protocol)
        manifest, _ = load_v24_manifest(args.manifest)
        _ensure_preaccess_state()
        source_hashes = {
            relative: sha256_file(resolve_within_root(relative, "mechanism-v2.4 frozen source"))
            for relative in FROZEN_SOURCE_FILES
        }
        predecessor = protocol["predecessor_invalidation"]
        morpho_provenance = protocol["morpho_mapping_provenance"]
        receipt = {
            "receipt_id": "mechanism-v2.4-pre-access-freeze-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": protocol["protocol_id"],
            "protocol_path": str(args.protocol.relative_to(ROOT)),
            "protocol_sha256": sha256_file(args.protocol),
            "data_manifest_path": str(args.manifest.relative_to(ROOT)),
            "data_manifest_sha256": sha256_file(args.manifest),
            "predecessor_invalidation_path": predecessor["receipt_path"],
            "predecessor_invalidation_sha256": predecessor["receipt_sha256"],
            "morpho_structural_discovery_sha256": morpho_provenance["structural_discovery"]["result_sha256"],
            "morpho_semantic_discovery_sha256": morpho_provenance["semantic_discovery"]["result_sha256"],
            "historical_e7_source_receipt_sha256": protocol["historical_e7_binding"]["source_receipt_sha256"],
            "historical_e7_strict_cache_manifest_sha256": protocol["historical_e7_binding"]["strict_cache_manifest_sha256"],
            "frozen_morpho_mapping_id": external_mapping(protocol, "morpho_fod7")["mapping_id"],
            "frozen_morpho_mapping_sha256": json_hash(external_mapping(protocol, "morpho_fod7")),
            "frozen_coqtel_mapping_id": external_mapping(protocol, "coqtel_corrosion")["mapping_id"],
            "frozen_coqtel_mapping_sha256": json_hash(external_mapping(protocol, "coqtel_corrosion")),
            "code_revision_at_freeze": _git_revision(),
            "frozen_source_files": list(FROZEN_SOURCE_FILES),
            "frozen_source_sha256": source_hashes,
            "new_waveform_access_before_receipt": False,
            "schema_mapping_selected_before_receipt": True,
            "d04_d24_excluded_from_v2_4_receipts_and_confirmation": True,
            "datasets_at_freeze": [
                {
                    "dataset_id": entry["dataset_id"],
                    "data_role": entry["role"],
                    "access_state_at_v2_4_freeze": entry.get("access_state_at_v2_4_freeze"),
                }
                for entry in manifest["data_sets"]
            ],
        }
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    except (V24Error, OSError) as error:
        print(f"MECHANISM-V2.4 FREEZE FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
