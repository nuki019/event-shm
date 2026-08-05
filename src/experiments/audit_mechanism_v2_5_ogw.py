"""Read-only audit for one-shot mechanism-v2.5 OGW confirmations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments import audit_mechanism_v2 as base
from src.experiments import mechanism_v2_5_successor as v25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=v25.ROOT / "protocols" / "mechanism_v2_5.json")
    parser.add_argument("--manifest", type=Path, default=v25.ROOT / "protocols" / "mechanism_v2_5_data_manifest.json")
    parser.add_argument("--freeze-receipt", type=Path, default=v25.ROOT / "protocols" / "mechanism_v2_5_freeze_receipt.json")
    parser.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def audit_result(protocol_path: Path, manifest_path: Path, freeze_path: Path, result_path: Path) -> None:
    protocol_file = v25.resolve_within_root(protocol_path, "v2.5 OGW audit protocol")
    manifest_file = v25.resolve_within_root(manifest_path, "v2.5 OGW audit manifest")
    freeze_file = v25.resolve_within_root(freeze_path, "v2.5 OGW audit freeze receipt")
    result_file = v25.resolve_within_root(result_path, "v2.5 OGW audit result")
    protocol = v25.verify_v25_freeze(protocol_file, manifest_file, freeze_file)
    manifest, _ = v25.load_v25_manifest(manifest_file)
    result = v25.load_json(result_file)
    if result.get("freeze_receipt_sha256") != v25.sha256_file(freeze_file):
        raise base.AuditError("v2.5 OGW result is not bound to the frozen receipt")
    if result.get("result_schema_sha256") != protocol["result_schema"]["sha256"]:
        raise base.AuditError("v2.5 OGW result is not bound to the frozen result schema")
    original_loader = base._load_json
    was_supported = v25.PROTOCOL_ID in base.SUPPORTED_PROTOCOL_IDS
    base.SUPPORTED_PROTOCOL_IDS.add(v25.PROTOCOL_ID)

    def loader(path: Path) -> dict:
        resolved = Path(path).resolve()
        if resolved == protocol_file:
            return protocol
        if resolved == manifest_file:
            return manifest
        return original_loader(path)

    base._load_json = loader
    try:
        base.audit_result(protocol_file, manifest_file, result_file)
    finally:
        base._load_json = original_loader
        if not was_supported:
            base.SUPPORTED_PROTOCOL_IDS.discard(v25.PROTOCOL_ID)


def main() -> int:
    args = parse_args()
    try:
        audit_result(args.protocol, args.manifest, args.freeze_receipt, args.result)
    except (base.AuditError, v25.V25Error) as error:
        print(f"MECHANISM-V2.5 OGW AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    print(f"mechanism-v2.5 OGW audit passed: {args.result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
