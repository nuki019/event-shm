"""Write one-time metadata-only v2.5 MORPHO or COQTEL schema-gate evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.data.mechanism_v2_5_external_schema import audit_coqtel_corrosion, audit_morpho_fod7
from src.experiments.mechanism_v2_5_successor import (
    ROOT, V25Error, external_mapping, load_json, load_v25_manifest, manifest_entry, resolve_within_root, sha256_file, verify_v25_freeze,
)


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_5.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_5_data_manifest.json"
DEFAULT_FREEZE = ROOT / "protocols" / "mechanism_v2_5_freeze_receipt.json"


class SchemaAuditError(RuntimeError):
    """Raised when a v2.5 schema gate cannot be safely attempted."""


def _receipt_paths(receipt_path: Path, dataset_id: str, manifest: dict[str, Any]) -> tuple[dict[str, Any], list[Path]]:
    receipt = load_json(receipt_path)
    if receipt.get("protocol_id") != "mechanism-v2.5" or receipt.get("dataset_id") != dataset_id:
        raise SchemaAuditError("source receipt does not identify the requested v2.5 dataset")
    if receipt.get("waveform_access_permitted") is not True:
        raise SchemaAuditError("source receipt does not permit the metadata-only HDF5 gate")
    entry = manifest_entry(manifest, dataset_id)
    if receipt.get("data_role") != entry.get("role"):
        raise SchemaAuditError("source receipt data role differs from frozen manifest")
    files = receipt.get("archive_and_content_hashes")
    expected = {str(item["filename"]) for item in entry.get("files", []) if isinstance(item, dict) and isinstance(item.get("filename"), str)}
    if not isinstance(files, list) or not files or not expected:
        raise SchemaAuditError("source receipt or frozen manifest lacks verified files")
    h5_paths: list[Path] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise SchemaAuditError("source receipt contains a malformed file entry")
        filename, value, expected_sha = item.get("filename"), item.get("path"), item.get("sha256")
        if not isinstance(filename, str) or not isinstance(value, str) or not isinstance(expected_sha, str):
            raise SchemaAuditError("source receipt file entry is incomplete")
        if filename not in expected or item.get("md5_verified_before_waveform_access") is not True:
            raise SchemaAuditError("source receipt contains an unmanifested or unverified file")
        path = resolve_within_root(value, "v2.5 verified source")
        if sha256_file(path) != expected_sha:
            raise SchemaAuditError(f"source file SHA-256 changed after its v2.5 receipt: {path}")
        seen.add(filename)
        if filename.lower().endswith(".h5"):
            h5_paths.append(path)
    if seen != expected:
        raise SchemaAuditError("source receipt file set differs from frozen manifest")
    return receipt, sorted(h5_paths, key=lambda path: path.name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("morpho_fod7", "coqtel_corrosion"), required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--access-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        protocol_path = resolve_within_root(args.protocol, "v2.5 schema protocol")
        manifest_path = resolve_within_root(args.manifest, "v2.5 schema manifest")
        freeze_path = resolve_within_root(args.freeze_receipt, "v2.5 schema freeze receipt")
        access_path = resolve_within_root(args.access_receipt, "v2.5 source receipt")
        output = resolve_within_root(args.output, "v2.5 schema gate output", must_exist=False)
        if output.exists():
            raise SchemaAuditError(f"refusing to overwrite schema gate receipt: {output}")
        protocol = verify_v25_freeze(protocol_path, manifest_path, freeze_path)
        manifest, _ = load_v25_manifest(manifest_path)
        entry = manifest_entry(manifest, args.dataset)
        receipt, h5_paths = _receipt_paths(access_path, args.dataset, manifest)
        if args.dataset == "morpho_fod7":
            if len(h5_paths) != 1:
                raise SchemaAuditError("MORPHO schema gate requires exactly one verified HDF5 source")
            gate = audit_morpho_fod7(h5_paths[0], external_mapping(protocol, args.dataset))
        else:
            if len(h5_paths) != 2:
                raise SchemaAuditError("COQTEL schema gate requires exactly two verified HDF5 campaigns")
            gate = audit_coqtel_corrosion(h5_paths, external_mapping(protocol, args.dataset))
        result = {
            "schema_audit_id": f"mechanism-v2.5-{args.dataset}-metadata-schema-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": protocol["protocol_id"], "protocol_sha256": sha256_file(protocol_path),
            "data_manifest_sha256": sha256_file(manifest_path), "freeze_receipt_sha256": sha256_file(freeze_path),
            "outcome_type": "metadata_only_schema_gate",
            "data": {"dataset_id": args.dataset, "data_role": entry["role"], "archive_and_content_hashes": receipt["archive_and_content_hashes"], "hdf5_campaign_paths": [str(path.relative_to(ROOT)) for path in h5_paths]},
            "schema_gate": gate,
            "selection_receipt": {
                "discovery_data_used_for_selection": False, "posthoc_configuration_selection": False,
                "mapping_is_hashed_inside_the_frozen_v2_5_protocol": True, "waveform_scoring_started": False,
                "waveform_values_read": False, "metadata_values_read": False, "attribute_values_read": False,
                "schema_failure_is_not_a_signal_result": True,
            },
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (SchemaAuditError, V25Error, OSError) as error:
        print(f"MECHANISM-V2.5 EXTERNAL SCHEMA GATE FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {output} ({gate['status']})")
    return 0 if gate["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
