"""Write the frozen v2.2 COQTEL hierarchical metadata-only schema receipt."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.data.mechanism_hdf5_schema_v2_2 import audit_coqtel_hierarchy
from src.experiments.download_mechanism_v2_data import DownloadError, _resolve_within_workspace
from src.experiments.mechanism_v2_2_successor import (
    ROOT,
    SUCCESSOR_PROTOCOL_ID,
    SuccessorError,
    external_mapping,
    load_json,
    load_successor_manifest,
    load_successor_protocol,
    manifest_entry,
    sha256_file,
    verify_successor_freeze,
)


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_2.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_2_data_manifest.json"
DEFAULT_FREEZE_RECEIPT = ROOT / "protocols" / "mechanism_v2_2_freeze_receipt.json"


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _receipt_h5_paths(receipt_path: Path, dataset_id: str) -> tuple[dict[str, Any], list[Path]]:
    receipt = load_json(receipt_path)
    if receipt.get("protocol_id") != SUCCESSOR_PROTOCOL_ID or receipt.get("dataset_id") != dataset_id:
        raise SuccessorError("successor access receipt does not identify COQTEL under v2.2")
    if receipt.get("waveform_access_permitted") is not True:
        raise SuccessorError("successor access receipt does not permit metadata inspection")
    files = receipt.get("archive_and_content_hashes")
    if not isinstance(files, list):
        raise SuccessorError("successor access receipt has no file hashes")
    paths: list[Path] = []
    for item in files:
        if not isinstance(item, dict) or item.get("md5_verified_before_waveform_access") is not True:
            raise SuccessorError("successor access receipt lacks pre-access MD5 evidence")
        filename = item.get("filename")
        value = item.get("path")
        if not (isinstance(filename, str) and isinstance(value, str)):
            raise SuccessorError("successor access receipt has an incomplete file entry")
        if filename.endswith(".h5"):
            path = _resolve_within_workspace(Path(value), "HDF5 source")
            if not path.is_file():
                raise SuccessorError(f"verified HDF5 source is absent: {path}")
            paths.append(path)
    if len(paths) != 2:
        raise SuccessorError("COQTEL schema audit requires exactly two verified HDF5 campaigns")
    return receipt, sorted(paths, key=lambda path: path.name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--access-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        args.protocol = _resolve_within_workspace(args.protocol, "protocol")
        args.manifest = _resolve_within_workspace(args.manifest, "manifest")
        args.freeze_receipt = _resolve_within_workspace(args.freeze_receipt, "freeze receipt")
        args.access_receipt = _resolve_within_workspace(args.access_receipt, "access receipt")
        args.output = _resolve_within_workspace(args.output, "output")
        if args.output.exists():
            raise SuccessorError(f"refusing to overwrite schema receipt: {args.output}")
        protocol = verify_successor_freeze(args.protocol, args.manifest, args.freeze_receipt)
        manifest, _ = load_successor_manifest(args.manifest)
        entry = manifest_entry(manifest, "coqtel_corrosion")
        if entry.get("role") != "material_independent_confirmation":
            raise SuccessorError("resolved COQTEL role differs from the frozen successor protocol")
        access_receipt, h5_paths = _receipt_h5_paths(args.access_receipt, "coqtel_corrosion")
        mapping = external_mapping(protocol, "coqtel_corrosion")
        gate = audit_coqtel_hierarchy(h5_paths, mapping)
        result = {
            "schema_audit_id": f"{SUCCESSOR_PROTOCOL_ID}-coqtel-hierarchical-schema-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": SUCCESSOR_PROTOCOL_ID,
            "protocol_sha256": sha256_file(args.protocol),
            "data_manifest_sha256": sha256_file(args.manifest),
            "code_revision": _git_revision(),
            "outcome_type": "schema_gate",
            "data": {
                "dataset_id": "coqtel_corrosion",
                "data_role": entry["role"],
                "archive_and_content_hashes": access_receipt["archive_and_content_hashes"],
                "hdf5_campaign_paths": [str(path.relative_to(ROOT)) for path in h5_paths],
            },
            "schema_gate": gate,
            "selection_receipt": {
                "discovery_data_used_for_selection": False,
                "posthoc_configuration_selection": False,
                "mapping_is_hashed_inside_the_frozen_successor_protocol": True,
                "waveform_scoring_started": False,
                "waveform_values_read": False,
                "metadata_values_read": False,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (DownloadError, SuccessorError) as error:
        print(f"{SUCCESSOR_PROTOCOL_ID.upper()} HDF5 SCHEMA AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.output} ({gate['status']})")
    return 0 if gate["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
