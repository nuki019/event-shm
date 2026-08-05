"""Create an immutable pre-access receipt for the mechanism-v2 protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_data_manifest.json"
DEFAULT_RECEIPT = ROOT / "protocols" / "mechanism_v2_freeze_receipt.json"
SUPPORTED_PROTOCOL_IDS = {"mechanism-v2", "mechanism-v2.1"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_within_workspace(path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError as error:
        raise SystemExit(f"{label} must lie under the workspace root: {path}") from error
    return resolved


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    args.protocol = _resolve_within_workspace(args.protocol, "protocol")
    args.manifest = _resolve_within_workspace(args.manifest, "manifest")
    args.receipt = _resolve_within_workspace(args.receipt, "receipt")
    if args.receipt.exists():
        raise SystemExit(f"refusing to overwrite existing freeze receipt: {args.receipt}")
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    protocol_id = protocol.get("protocol_id")
    if protocol_id not in SUPPORTED_PROTOCOL_IDS or protocol.get("status") != "frozen_before_new_waveform_access":
        raise SystemExit("protocol is not a supported frozen mechanism-v2 protocol")
    datasets = manifest.get("data_sets")
    if not isinstance(datasets, list):
        raise SystemExit("data manifest lacks data_sets")
    receipt = {
        "receipt_id": f"{protocol_id}-pre-access-freeze-v1",
        "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "protocol_id": protocol_id,
        "protocol_path": str(args.protocol.relative_to(ROOT)),
        "protocol_sha256": _sha256(args.protocol),
        "data_manifest_path": str(args.manifest.relative_to(ROOT)),
        "data_manifest_sha256": _sha256(args.manifest),
        "code_revision_at_freeze": _git_revision(),
        "frozen_source_files": [
            "src/methods/strict_codecs.py",
            "src/methods/mechanism_v2.py",
            "src/data/mechanism_hdf5_schema.py",
            "src/experiments/audit_mechanism_v2.py",
            "src/experiments/e9_mechanism_v2_ogw.py",
            "src/experiments/download_mechanism_v2_data.py"
        ],
        "new_waveform_access_before_receipt": False,
        "datasets_at_freeze": [
            {
                "dataset_id": entry.get("dataset_id"),
                "role": entry.get("role"),
                "access_state_at_freeze": entry.get("access_state_at_freeze"),
            }
            for entry in datasets
            if isinstance(entry, dict)
        ],
    }
    receipt["frozen_source_sha256"] = {
        relative: _sha256(ROOT / relative)
        for relative in receipt["frozen_source_files"]
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"saved {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
