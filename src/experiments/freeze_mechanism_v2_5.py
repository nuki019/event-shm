"""Create the immutable pre-access freeze receipt for mechanism-v2.5."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.mechanism_v2_5_successor import (
    ROOT, V25Error, external_execution_contract, external_mapping, json_hash, load_v25_manifest, load_v25_protocol,
    resolve_within_root, sha256_file,
)


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_5.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_5_data_manifest.json"
DEFAULT_RECEIPT = ROOT / "protocols" / "mechanism_v2_5_freeze_receipt.json"
FROZEN_SOURCE_FILES = (
    "src/data/mechanism_hdf5_metadata_safe_v2_5.py",
    "src/data/mechanism_v2_5_external_schema.py",
    "src/data/ogw_loader.py",
    "src/methods/strict_codecs.py",
    "src/methods/mechanism_v2.py",
    "src/experiments/e7_strict_codec_benchmark.py",
    "src/experiments/e9_mechanism_v2_ogw.py",
    "src/experiments/audit_mechanism_v2.py",
    "src/experiments/mechanism_v2_5_successor.py",
    "src/experiments/verify_mechanism_v2_5_source.py",
    "src/experiments/audit_mechanism_v2_5_external_schema.py",
    "src/experiments/bind_mechanism_v2_5_calibration.py",
    "src/experiments/e9_mechanism_v2_5_ogw.py",
    "src/experiments/e9_mechanism_v2_5_morpho.py",
    "src/experiments/audit_mechanism_v2_5_ogw.py",
    "src/experiments/audit_mechanism_v2_5.py",
    "src/experiments/audit_mechanism_v2_5_preflight.py",
    "src/experiments/freeze_mechanism_v2_5.py",
)
PREACCESS_ARTIFACTS = (
    "mechanism_v2_5_ogw_d12_source_receipt.json",
    "mechanism_v2_5_ogw_d16_source_receipt.json",
    "mechanism_v2_5_morpho_source_receipt.json",
    "mechanism_v2_5_coqtel_source_receipt.json",
    "mechanism_v2_5_ogw_udam_calibration_binding.json",
    "mechanism_v2_5_morpho_schema_gate.json",
    "mechanism_v2_5_coqtel_schema_gate.json",
    "mechanism_v2_5_preexperiment_audit.json",
    "mechanism_v2_5_ogw_d12_confirmation.json",
    "mechanism_v2_5_ogw_d16_confirmation.json",
    "mechanism_v2_5_morpho_confirmation.json",
)


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _ensure_preaccess_state() -> None:
    occupied = [name for name in PREACCESS_ARTIFACTS if (ROOT / "results" / name).exists()]
    caches = [ROOT / "data" / "interim" / name for name in ("mechanism_v2_5_ogw_d12", "mechanism_v2_5_ogw_d16", "mechanism_v2_5_morpho")]
    occupied_caches = [str(path.relative_to(ROOT)) for path in caches if path.exists()]
    if occupied or occupied_caches:
        raise V25Error(f"v2.5 freeze must precede receipts/results/caches; artifacts={occupied}; caches={occupied_caches}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        protocol_path = resolve_within_root(args.protocol, "mechanism-v2.5 protocol")
        manifest_path = resolve_within_root(args.manifest, "mechanism-v2.5 data manifest")
        receipt_candidate = args.receipt if args.receipt.is_absolute() else ROOT / args.receipt
        receipt_path = resolve_within_root(receipt_candidate, "mechanism-v2.5 freeze receipt", must_exist=False)
        if receipt_path.exists():
            raise V25Error(f"refusing to overwrite mechanism-v2.5 freeze receipt: {receipt_path}")
        protocol, _ = load_v25_protocol(protocol_path)
        manifest, _ = load_v25_manifest(manifest_path)
        _ensure_preaccess_state()
        source_hashes = {relative: sha256_file(resolve_within_root(relative, "mechanism-v2.5 frozen source")) for relative in FROZEN_SOURCE_FILES}
        receipt = {
            "receipt_id": "mechanism-v2.5-pre-access-freeze-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": protocol["protocol_id"], "protocol_path": str(protocol_path.relative_to(ROOT)), "protocol_sha256": sha256_file(protocol_path),
            "data_manifest_path": str(manifest_path.relative_to(ROOT)), "data_manifest_sha256": sha256_file(manifest_path),
            "result_schema_path": protocol["result_schema"]["path"], "result_schema_sha256": protocol["result_schema"]["sha256"],
            "predecessor_invalidation_path": protocol["predecessor_invalidation"]["receipt_path"], "predecessor_invalidation_sha256": protocol["predecessor_invalidation"]["receipt_sha256"],
            "morpho_structural_discovery_sha256": protocol["morpho_mapping_provenance"]["structural_discovery"]["result_sha256"],
            "morpho_semantic_discovery_sha256": protocol["morpho_mapping_provenance"]["semantic_discovery"]["result_sha256"],
            "historical_e7_source_receipt_sha256": protocol["historical_e7_binding"]["source_receipt_sha256"], "historical_e7_strict_cache_manifest_sha256": protocol["historical_e7_binding"]["strict_cache_manifest_sha256"],
            "frozen_morpho_mapping_id": external_mapping(protocol, "morpho_fod7")["mapping_id"], "frozen_morpho_mapping_sha256": json_hash(external_mapping(protocol, "morpho_fod7")),
            "frozen_coqtel_mapping_id": external_mapping(protocol, "coqtel_corrosion")["mapping_id"], "frozen_coqtel_mapping_sha256": json_hash(external_mapping(protocol, "coqtel_corrosion")),
            "frozen_external_execution_contract_sha256": json_hash(external_execution_contract(protocol)), "code_revision_at_freeze": _git_revision(),
            "frozen_source_files": list(FROZEN_SOURCE_FILES), "frozen_source_sha256": source_hashes,
            "new_waveform_access_before_receipt": False, "schema_mapping_selected_before_receipt": True,
            "d04_d24_excluded_from_v2_5_receipts_and_confirmation": True,
            "datasets_at_freeze": [{"dataset_id": item["dataset_id"], "data_role": item["role"], "access_state_at_v2_5_freeze": item.get("access_state_at_v2_5_freeze")} for item in manifest["data_sets"]],
        }
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    except (V25Error, OSError) as error:
        print(f"MECHANISM-V2.5 FREEZE FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
