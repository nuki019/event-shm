"""Re-bind a frozen source to a mechanism-v2.2 successor access receipt."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.download_mechanism_v2_data import DownloadError, _files, _resolve_within_workspace, _verify_and_finalize
from src.experiments.mechanism_v2_2_successor import (
    ROOT,
    SUCCESSOR_PROTOCOL_ID,
    SuccessorError,
    load_successor_manifest,
    manifest_entry,
    sha256_file,
    verify_successor_freeze,
)


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_2.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_2_data_manifest.json"
DEFAULT_FREEZE_RECEIPT = ROOT / "protocols" / "mechanism_v2_2_freeze_receipt.json"
DEFAULT_DESTINATION = ROOT / "data" / "external" / "mechanism_v2_2"


def _receipt(dataset: dict[str, Any], files: list[dict[str, Any]], protocol_path: Path, manifest_path: Path, dry_run: bool) -> dict[str, Any]:
    return {
        "receipt_id": f"{SUCCESSOR_PROTOCOL_ID}-download-verification-v1",
        "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "protocol_id": SUCCESSOR_PROTOCOL_ID,
        "protocol_sha256": sha256_file(protocol_path),
        "data_manifest_sha256": sha256_file(manifest_path),
        "dataset_id": dataset["dataset_id"],
        "data_role": dataset["role"],
        "waveform_access_permitted": not dry_run,
        "archive_and_content_hashes": files,
        "predecessor_receipts_reused_for_scoring": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="dataset_id from the resolved v2.2 data manifest")
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        args.protocol = _resolve_within_workspace(args.protocol, "protocol")
        args.manifest = _resolve_within_workspace(args.manifest, "manifest")
        args.freeze_receipt = _resolve_within_workspace(args.freeze_receipt, "freeze receipt")
        args.destination = _resolve_within_workspace(args.destination, "destination")
        args.receipt = _resolve_within_workspace(args.receipt, "receipt")
        if args.receipt.exists():
            raise DownloadError(f"refusing to overwrite successor receipt: {args.receipt}")
        verify_successor_freeze(args.protocol, args.manifest, args.freeze_receipt)
        manifest, _ = load_successor_manifest(args.manifest)
        dataset = manifest_entry(manifest, args.dataset)
        files = [_verify_and_finalize(item, args.destination, args.dry_run) for item in _files(dataset)]
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(_receipt(dataset, files, args.protocol, args.manifest, args.dry_run), indent=2) + "\n", encoding="utf-8")
    except (DownloadError, SuccessorError) as error:
        print(f"{SUCCESSOR_PROTOCOL_ID.upper()} DOWNLOAD FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
