"""Write a one-time metadata-only v2.4 external schema gate receipt."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.data.mechanism_v2_4_external_schema import audit_coqtel_corrosion, audit_morpho_fod7
from src.experiments.mechanism_v2_4_successor import (
    ROOT,
    V24Error,
    external_mapping,
    load_json,
    load_v24_manifest,
    manifest_entry,
    resolve_within_root,
    sha256_file,
    verify_v24_freeze,
)


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_4.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_4_data_manifest.json"
DEFAULT_FREEZE_RECEIPT = ROOT / "protocols" / "mechanism_v2_4_freeze_receipt.json"


class SchemaAuditError(RuntimeError):
    """Raised when a v2.4 schema gate cannot safely be attempted."""


def _receipt_paths(receipt_path: Path, dataset_id: str, manifest: dict[str, Any]) -> tuple[dict[str, Any], list[Path]]:
    receipt = load_json(receipt_path)
    if receipt.get("protocol_id") != "mechanism-v2.4" or receipt.get("dataset_id") != dataset_id:
        raise SchemaAuditError("source receipt does not identify the requested v2.4 dataset")
    if receipt.get("waveform_access_permitted") is not True:
        raise SchemaAuditError("source receipt does not permit the metadata-only HDF5 gate")
    entry = manifest_entry(manifest, dataset_id)
    if receipt.get("data_role") != entry.get("role"):
        raise SchemaAuditError("source receipt data role differs from the frozen manifest")
    files = receipt.get("archive_and_content_hashes")
    if not isinstance(files, list) or not files:
        raise SchemaAuditError("source receipt lacks verified file hashes")
    expected = {str(item["filename"]) for item in entry.get("files", []) if isinstance(item, dict) and isinstance(item.get("filename"), str)}
    paths: list[Path] = []
    observed: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise SchemaAuditError("source receipt contains a malformed file entry")
        filename = item.get("filename")
        value = item.get("path")
        expected_sha = item.get("sha256")
        if not isinstance(filename, str) or not isinstance(value, str) or not isinstance(expected_sha, str):
            raise SchemaAuditError("source receipt file entry is incomplete")
        if item.get("md5_verified_before_waveform_access") is not True:
            raise SchemaAuditError("source receipt lacks an MD5-before-access assertion")
        if filename not in expected:
            raise SchemaAuditError(f"source receipt contains an unmanifested file: {filename}")
        path = resolve_within_root(value, "v2.4 verified source")
        if sha256_file(path) != expected_sha:
            raise SchemaAuditError(f"source file SHA-256 changed after its v2.4 receipt: {path}")
        observed.add(filename)
        if filename.lower().endswith(".h5"):
            paths.append(path)
    if observed != expected:
        raise SchemaAuditError("source receipt file set differs from the frozen manifest")
    return receipt, sorted(paths, key=lambda path: path.name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("morpho_fod7", "coqtel_corrosion"), required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--access-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        args.protocol = resolve_within_root(args.protocol, "mechanism-v2.4 protocol")
        args.manifest = resolve_within_root(args.manifest, "mechanism-v2.4 data manifest")
        args.freeze_receipt = resolve_within_root(args.freeze_receipt, "mechanism-v2.4 freeze receipt")
        args.access_receipt = resolve_within_root(args.access_receipt, "mechanism-v2.4 source receipt")
        args.output = resolve_within_root(args.output, "mechanism-v2.4 schema gate output", must_exist=False)
        if args.output.exists():
            raise SchemaAuditError(f"refusing to overwrite schema gate receipt: {args.output}")
        protocol = verify_v24_freeze(args.protocol, args.manifest, args.freeze_receipt)
        manifest, _ = load_v24_manifest(args.manifest)
        entry = manifest_entry(manifest, args.dataset)
        receipt, h5_paths = _receipt_paths(args.access_receipt, args.dataset, manifest)
        if args.dataset == "morpho_fod7":
            if len(h5_paths) != 1:
                raise SchemaAuditError("MORPHO schema gate requires exactly one verified HDF5 source")
            gate = audit_morpho_fod7(h5_paths[0], external_mapping(protocol, args.dataset))
        else:
            if len(h5_paths) != 2:
                raise SchemaAuditError("COQTEL schema gate requires exactly two verified HDF5 campaigns")
            gate = audit_coqtel_corrosion(h5_paths, external_mapping(protocol, args.dataset))
        result = {
            "schema_audit_id": f"mechanism-v2.4-{args.dataset}-metadata-schema-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": sha256_file(args.protocol),
            "data_manifest_sha256": sha256_file(args.manifest),
            "freeze_receipt_sha256": sha256_file(args.freeze_receipt),
            "outcome_type": "metadata_only_schema_gate",
            "data": {
                "dataset_id": args.dataset,
                "data_role": entry["role"],
                "archive_and_content_hashes": receipt["archive_and_content_hashes"],
                "hdf5_campaign_paths": [str(path.relative_to(ROOT)) for path in h5_paths],
            },
            "schema_gate": gate,
            "selection_receipt": {
                "discovery_data_used_for_selection": False,
                "posthoc_configuration_selection": False,
                "mapping_is_hashed_inside_the_frozen_v2_4_protocol": True,
                "waveform_scoring_started": False,
                "waveform_values_read": False,
                "metadata_values_read": False,
                "attribute_values_read": False,
                "schema_failure_is_not_a_signal_result": True,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (SchemaAuditError, V24Error, OSError) as error:
        print(f"MECHANISM-V2.4 EXTERNAL SCHEMA GATE FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.output} ({gate['status']})")
    return 0 if gate["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
