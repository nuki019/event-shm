"""Verify an already local frozen source before allowing mechanism-v2 access."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_data_manifest.json"
DEFAULT_FREEZE_RECEIPT = ROOT / "protocols" / "mechanism_v2_freeze_receipt.json"


def _sha(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def _entry(manifest: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    entries = manifest.get("data_sets")
    if not isinstance(entries, list):
        raise ValueError("manifest lacks data_sets")
    matches = [item for item in entries if isinstance(item, dict) and item.get("dataset_id") == dataset_id]
    if len(matches) != 1:
        raise ValueError(f"dataset {dataset_id} is absent or duplicated")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = _load(args.manifest)
        freeze = _load(args.freeze_receipt)
        manifest_hash = _sha(args.manifest, "sha256")
        if freeze.get("data_manifest_sha256") != manifest_hash:
            raise ValueError("freeze receipt differs from manifest")
        entry = _entry(manifest, args.dataset)
        official = entry.get("official")
        if not isinstance(official, dict):
            raise ValueError("dataset has no official source metadata")
        filename = official.get("archive_filename")
        checksum = official.get("official_checksum")
        expected_size = official.get("size_bytes")
        if not (isinstance(filename, str) and isinstance(checksum, dict) and isinstance(expected_size, int)):
            raise ValueError("dataset does not describe one verifiable local archive")
        if args.path.name != filename or not args.path.is_file():
            raise ValueError("local path does not match the frozen archive filename")
        if args.path.stat().st_size != expected_size:
            raise ValueError("local archive size differs from frozen manifest")
        md5 = _sha(args.path, "md5")
        if checksum.get("algorithm") != "md5" or md5 != checksum.get("value"):
            raise ValueError("local archive MD5 differs from frozen manifest")
        if args.receipt.exists():
            raise ValueError(f"refusing to overwrite existing receipt: {args.receipt}")
        try:
            stored_path = str(args.path.relative_to(ROOT))
        except ValueError:
            stored_path = str(args.path)
        receipt = {
            "receipt_id": "mechanism-v2-existing-source-verification-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_sha256": freeze.get("protocol_sha256"),
            "data_manifest_sha256": manifest_hash,
            "dataset_id": entry["dataset_id"],
            "data_role": entry["role"],
            "waveform_access_permitted": True,
            "archive_and_content_hashes": [
                {
                    "filename": filename,
                    "path": stored_path,
                    "size_bytes": expected_size,
                    "md5": md5,
                    "sha256": _sha(args.path, "sha256"),
                    "md5_verified_before_waveform_access": True,
                }
            ],
        }
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"MECHANISM-V2 SOURCE VERIFICATION FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
