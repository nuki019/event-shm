"""Read-only audit entry point for one-shot mechanism-v2.4 confirmations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments import audit_mechanism_v2 as base
from src.experiments import mechanism_v2_4_successor as v24


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=v24.ROOT / "protocols" / "mechanism_v2_4.json")
    parser.add_argument("--manifest", type=Path, default=v24.ROOT / "protocols" / "mechanism_v2_4_data_manifest.json")
    parser.add_argument("--freeze-receipt", type=Path, default=v24.ROOT / "protocols" / "mechanism_v2_4_freeze_receipt.json")
    parser.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def audit_result(protocol_path: Path, manifest_path: Path, freeze_path: Path, result_path: Path) -> None:
    protocol_file = v24.resolve_within_root(protocol_path, "v2.4 audit protocol")
    manifest_file = v24.resolve_within_root(manifest_path, "v2.4 audit manifest")
    freeze_file = v24.resolve_within_root(freeze_path, "v2.4 audit freeze receipt")
    result_file = v24.resolve_within_root(result_path, "v2.4 audit result")
    protocol = v24.verify_v24_freeze(protocol_file, manifest_file, freeze_file)
    manifest, _ = v24.load_v24_manifest(manifest_file)
    original_loader = base._load_json
    base.SUPPORTED_PROTOCOL_IDS.add(v24.PROTOCOL_ID)

    def v24_loader(path: Path) -> dict:
        resolved = Path(path).resolve()
        if resolved == protocol_file:
            return protocol
        if resolved == manifest_file:
            return manifest
        return original_loader(path)

    base._load_json = v24_loader
    try:
        base.audit_result(protocol_file, manifest_file, result_file)
    finally:
        base._load_json = original_loader


def main() -> int:
    args = parse_args()
    try:
        audit_result(args.protocol, args.manifest, args.freeze_receipt, args.result)
    except (base.AuditError, v24.V24Error) as error:
        print(f"MECHANISM-V2.4 AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    print(f"mechanism-v2.4 audit passed: {args.result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
