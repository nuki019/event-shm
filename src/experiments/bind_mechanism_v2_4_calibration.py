"""Bind immutable E7 healthy calibration evidence into mechanism-v2.4.

The binding does not rebuild E7 or change its cache.  It rechecks the pinned
undamaged ZIP SHA-256, pins the frozen strict-cache manifest, and produces a
new v2.4 receipt so an E9 runner never treats an older protocol's receipt as
fresh authorization.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.mechanism_v2_4_successor import (
    ROOT,
    V24Error,
    load_json,
    manifest_entry,
    resolve_within_root,
    sha256_file,
    verify_v24_freeze,
)


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_4.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_4_data_manifest.json"
DEFAULT_FREEZE_RECEIPT = ROOT / "protocols" / "mechanism_v2_4_freeze_receipt.json"
DEFAULT_OUTPUT = ROOT / "results" / "mechanism_v2_4_ogw_udam_calibration_binding.json"


class CalibrationBindingError(RuntimeError):
    """Raised when the immutable E7 calibration provenance cannot be bound."""


def _reverify_files(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    files = receipt.get("archive_and_content_hashes")
    if not isinstance(files, list) or len(files) != 1:
        raise CalibrationBindingError("historical E7 source receipt must contain exactly one archive")
    item = files[0]
    if not isinstance(item, dict) or item.get("md5_verified_before_waveform_access") is not True:
        raise CalibrationBindingError("historical E7 source receipt lacks MD5-before-access evidence")
    value = item.get("path")
    expected = item.get("sha256")
    if not isinstance(value, str) or not isinstance(expected, str):
        raise CalibrationBindingError("historical E7 source receipt lacks archive path/SHA-256")
    path = resolve_within_root(value, "historical E7 archive")
    if sha256_file(path) != expected:
        raise CalibrationBindingError("historical E7 archive SHA-256 differs from the pinned receipt")
    return [dict(item)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        args.protocol = resolve_within_root(args.protocol, "mechanism-v2.4 protocol")
        args.manifest = resolve_within_root(args.manifest, "mechanism-v2.4 manifest")
        args.freeze_receipt = resolve_within_root(args.freeze_receipt, "mechanism-v2.4 freeze receipt")
        args.output = resolve_within_root(args.output, "mechanism-v2.4 calibration binding", must_exist=False)
        if args.output.exists():
            raise CalibrationBindingError(f"refusing to overwrite calibration binding: {args.output}")
        protocol = verify_v24_freeze(args.protocol, args.manifest, args.freeze_receipt)
        binding = protocol["historical_e7_binding"]
        historical_path = resolve_within_root(binding["source_receipt_path"], "historical E7 source receipt")
        historical = load_json(historical_path)
        if historical.get("dataset_id") != "ogw_cfrp_temperature_udam":
            raise CalibrationBindingError("historical receipt does not identify the undamaged OGW archive")
        files = _reverify_files(historical)
        if manifest_entry(load_json(args.manifest), "ogw_cfrp_temperature_udam").get("role") != "preexisting_calibration_and_healthy_reference":
            raise CalibrationBindingError("v2.4 manifest changes the immutable E7 data role")
        result = {
            "receipt_id": "mechanism-v2.4-e7-calibration-binding-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": sha256_file(args.protocol),
            "data_manifest_sha256": sha256_file(args.manifest),
            "freeze_receipt_sha256": sha256_file(args.freeze_receipt),
            "dataset_id": "ogw_cfrp_temperature_udam",
            "data_role": "preexisting_calibration_and_healthy_reference",
            "waveform_access_permitted": True,
            "archive_and_content_hashes": files,
            "strict_cache_manifest_path": binding["strict_cache_manifest_path"],
            "strict_cache_manifest_sha256": binding["strict_cache_manifest_sha256"],
            "historical_receipt_path": str(historical_path.relative_to(ROOT)),
            "historical_receipt_sha256": sha256_file(historical_path),
            "e7_is_historical_and_not_new_confirmation": True,
            "raw_byte_hashing_only": True,
            "archive_contents_opened": False,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (CalibrationBindingError, V24Error, OSError) as error:
        print(f"MECHANISM-V2.4 CALIBRATION BINDING FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
