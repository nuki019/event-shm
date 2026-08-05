"""Create the immutable pre-access freeze receipt for mechanism-v2.3."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.mechanism_v2_3_successor import (
    ROOT,
    SUCCESSOR_PROTOCOL_ID,
    SuccessorError,
    external_mapping,
    json_hash,
    load_json,
    load_successor_manifest,
    load_successor_protocol,
    resolve_within_root,
    sha256_file,
)


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_3.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_3_data_manifest.json"
DEFAULT_RECEIPT = ROOT / "protocols" / "mechanism_v2_3_freeze_receipt.json"
FROZEN_SOURCE_FILES = (
    "src/data/ogw_loader.py",
    "src/data/ranged_download.py",
    "src/data/mechanism_hdf5_schema.py",
    "src/data/mechanism_hdf5_schema_v2_2.py",
    "src/methods/strict_codecs.py",
    "src/methods/mechanism_v2.py",
    "src/experiments/e7_strict_codec_benchmark.py",
    "src/experiments/audit_mechanism_v2.py",
    "src/experiments/e9_mechanism_v2_ogw.py",
    "src/experiments/download_mechanism_v2_data.py",
    "src/experiments/mechanism_v2_2_successor.py",
    "src/experiments/audit_mechanism_hdf5_schema_v2_2.py",
    "src/experiments/download_mechanism_v2_2_data.py",
    "src/experiments/e9_mechanism_v2_2_ogw.py",
    "src/experiments/audit_mechanism_v2_2.py",
    "src/experiments/mechanism_v2_3_successor.py",
    "src/experiments/audit_mechanism_hdf5_schema_v2_3.py",
    "src/experiments/download_mechanism_v2_3_data.py",
    "src/experiments/e9_mechanism_v2_3_ogw.py",
    "src/experiments/audit_mechanism_v2_3.py",
    "src/experiments/freeze_mechanism_v2_3.py",
)


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def _validate_predecessor_invalidation(overlay: dict, manifest_overlay: dict) -> tuple[Path, dict]:
    invalidation = overlay.get("predecessor_invalidation")
    if not isinstance(invalidation, dict):
        raise SuccessorError("successor protocol lacks predecessor invalidation")
    if manifest_overlay.get("predecessor_invalidation") != invalidation:
        raise SuccessorError("protocol and manifest do not pin the same predecessor invalidation")
    invalidation_path = resolve_within_root(str(invalidation.get("receipt_path")), "predecessor invalidation")
    if sha256_file(invalidation_path) != invalidation.get("receipt_sha256"):
        raise SuccessorError("predecessor invalidation receipt SHA-256 differs from v2.3 pin")
    payload = load_json(invalidation_path)
    if payload.get("invalidated_protocol_id") != "mechanism-v2.2":
        raise SuccessorError("v2.3 must pin the mechanism-v2.2 invalidation receipt")
    boundary = payload.get("evidence_boundary")
    if not isinstance(boundary, dict) or any(value is not False for value in boundary.values()):
        raise SuccessorError("v2.2 invalidation does not prove a pre-access recovery boundary")
    return invalidation_path, invalidation


def main() -> int:
    args = parse_args()
    try:
        args.protocol = resolve_within_root(args.protocol, "successor protocol")
        args.manifest = resolve_within_root(args.manifest, "successor data manifest")
        receipt_candidate = args.receipt if args.receipt.is_absolute() else ROOT / args.receipt
        try:
            args.receipt = receipt_candidate.resolve()
            args.receipt.relative_to(ROOT.resolve())
        except ValueError as error:
            raise SuccessorError("successor freeze receipt must lie inside the workspace") from error
        if args.receipt.exists():
            raise SuccessorError(f"refusing to overwrite freeze receipt: {args.receipt}")
        protocol, overlay = load_successor_protocol(args.protocol)
        manifest, manifest_overlay = load_successor_manifest(args.manifest)
        invalidation_path, _ = _validate_predecessor_invalidation(overlay, manifest_overlay)
        mapping = external_mapping(protocol, "coqtel_corrosion")
        if mapping.get("mapping_id") != "mechanism-v2.3-coqtel-hierarchical-schema-v1":
            raise SuccessorError("v2.3 COQTEL hierarchy mapping id differs from the declared successor mapping")
        source_hashes = {relative: sha256_file(resolve_within_root(relative, "frozen source")) for relative in FROZEN_SOURCE_FILES}
        receipt = {
            "receipt_id": "mechanism-v2.3-pre-access-freeze-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": SUCCESSOR_PROTOCOL_ID,
            "protocol_path": str(args.protocol.relative_to(ROOT)),
            "protocol_sha256": sha256_file(args.protocol),
            "data_manifest_path": str(args.manifest.relative_to(ROOT)),
            "data_manifest_sha256": sha256_file(args.manifest),
            "predecessor_invalidation_receipt": str(invalidation_path.relative_to(ROOT)),
            "predecessor_invalidation_sha256": sha256_file(invalidation_path),
            "inherited_protocol_sha256": overlay["inherits"]["protocol_sha256"],
            "inherited_manifest_sha256": manifest_overlay["inherits"]["manifest_sha256"],
            "code_revision_at_freeze": _git_revision(),
            "frozen_source_files": list(FROZEN_SOURCE_FILES),
            "frozen_source_sha256": source_hashes,
            "frozen_coqtel_mapping_id": mapping["mapping_id"],
            "frozen_coqtel_mapping_sha256": json_hash(mapping),
            "new_waveform_access_before_receipt": False,
            "predecessor_metadata_only_access": "COQTEL hierarchy and official reader-example text were inspected under invalidated v2.1 before any waveform-array dereference. The same structural mapping is re-declared in v2.3; no v2.2 receipt, gate, cache, score, or confirmation result is reused.",
            "datasets_at_freeze": [
                {
                    "dataset_id": entry.get("dataset_id"),
                    "role": entry.get("role"),
                    "access_state_at_v2_1_freeze": entry.get("access_state_at_freeze"),
                    "v2_3_requirement": "v2.3 MD5/SHA receipt required before metadata or waveform access",
                }
                for entry in manifest["data_sets"]
                if isinstance(entry, dict)
            ],
        }
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    except SuccessorError as error:
        print(f"MECHANISM-V2.3 FREEZE FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
