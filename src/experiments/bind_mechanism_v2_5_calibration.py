"""Bind immutable E7 healthy calibration evidence into mechanism-v2.5."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.mechanism_v2_5_successor import (
    ROOT, V25Error, load_json, load_v25_manifest, manifest_entry, resolve_within_root, sha256_file, verify_v25_freeze,
)


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_5.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_5_data_manifest.json"
DEFAULT_FREEZE = ROOT / "protocols" / "mechanism_v2_5_freeze_receipt.json"
DEFAULT_OUTPUT = ROOT / "results" / "mechanism_v2_5_ogw_udam_calibration_binding.json"


class CalibrationBindingError(RuntimeError):
    """Raised when immutable E7 calibration provenance cannot be rebound."""


def _reverify_files(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    files = receipt.get("archive_and_content_hashes")
    if not isinstance(files, list) or len(files) != 1:
        raise CalibrationBindingError("historical E7 source receipt must contain exactly one archive")
    item = files[0]
    if not isinstance(item, dict) or item.get("md5_verified_before_waveform_access") is not True:
        raise CalibrationBindingError("historical E7 source receipt lacks MD5-before-access evidence")
    value, expected = item.get("path"), item.get("sha256")
    if not isinstance(value, str) or not isinstance(expected, str):
        raise CalibrationBindingError("historical E7 receipt lacks archive path/SHA-256")
    if sha256_file(resolve_within_root(value, "historical E7 archive")) != expected:
        raise CalibrationBindingError("historical E7 archive SHA-256 differs from its pinned receipt")
    return [dict(item)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        protocol_path = resolve_within_root(args.protocol, "v2.5 protocol")
        manifest_path = resolve_within_root(args.manifest, "v2.5 manifest")
        freeze_path = resolve_within_root(args.freeze_receipt, "v2.5 freeze receipt")
        output = resolve_within_root(args.output, "v2.5 calibration binding", must_exist=False)
        if output.exists():
            raise CalibrationBindingError(f"refusing to overwrite v2.5 calibration binding: {output}")
        protocol = verify_v25_freeze(protocol_path, manifest_path, freeze_path)
        historical_path = resolve_within_root(protocol["historical_e7_binding"]["source_receipt_path"], "historical E7 source receipt")
        historical = load_json(historical_path)
        if historical.get("dataset_id") != "ogw_cfrp_temperature_udam":
            raise CalibrationBindingError("historical receipt does not identify the undamaged OGW archive")
        manifest, _ = load_v25_manifest(manifest_path)
        if manifest_entry(manifest, "ogw_cfrp_temperature_udam").get("role") != "preexisting_calibration_and_healthy_reference":
            raise CalibrationBindingError("v2.5 manifest changes the immutable E7 role")
        result = {
            "receipt_id": "mechanism-v2.5-e7-calibration-binding-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": protocol["protocol_id"], "protocol_sha256": sha256_file(protocol_path),
            "data_manifest_sha256": sha256_file(manifest_path), "freeze_receipt_sha256": sha256_file(freeze_path),
            "dataset_id": "ogw_cfrp_temperature_udam", "data_role": "preexisting_calibration_and_healthy_reference",
            "waveform_access_permitted": True, "archive_and_content_hashes": _reverify_files(historical),
            "strict_cache_manifest_path": protocol["historical_e7_binding"]["strict_cache_manifest_path"],
            "strict_cache_manifest_sha256": protocol["historical_e7_binding"]["strict_cache_manifest_sha256"],
            "historical_receipt_path": str(historical_path.relative_to(ROOT)), "historical_receipt_sha256": sha256_file(historical_path),
            "e7_is_historical_and_not_new_confirmation": True, "raw_byte_hashing_only": True, "archive_contents_opened": False,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (CalibrationBindingError, V25Error, OSError) as error:
        print(f"MECHANISM-V2.5 CALIBRATION BINDING FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
