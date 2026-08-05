"""Read-only result audit for mechanism-v2.2 successor overlays."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments import audit_mechanism_v2 as base
from src.experiments.mechanism_v2_2_successor import (
    ROOT,
    SUCCESSOR_PROTOCOL_ID,
    SuccessorError,
    load_successor_manifest,
    load_successor_protocol,
    resolve_within_root,
    verify_successor_freeze,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=ROOT / "protocols" / "mechanism_v2_2.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "protocols" / "mechanism_v2_2_data_manifest.json")
    parser.add_argument("--freeze-receipt", type=Path, default=ROOT / "protocols" / "mechanism_v2_2_freeze_receipt.json")
    parser.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def audit_result(protocol_path: Path, manifest_path: Path, freeze_path: Path, result_path: Path) -> None:
    protocol_file = resolve_within_root(protocol_path, "successor protocol")
    manifest_file = resolve_within_root(manifest_path, "successor data manifest")
    freeze_file = resolve_within_root(freeze_path, "successor freeze receipt")
    resolved_protocol, _ = load_successor_protocol(protocol_file)
    resolved_manifest, _ = load_successor_manifest(manifest_file)
    verify_successor_freeze(protocol_file, manifest_file, freeze_file)
    original_loader = base._load_json
    base.SUPPORTED_PROTOCOL_IDS.add(SUCCESSOR_PROTOCOL_ID)

    def successor_loader(path: Path) -> dict:
        resolved_path = Path(path).resolve()
        if resolved_path == protocol_file:
            return resolved_protocol
        if resolved_path == manifest_file:
            return resolved_manifest
        return original_loader(path)

    base._load_json = successor_loader
    try:
        base.audit_result(protocol_file, manifest_file, result_path)
    finally:
        base._load_json = original_loader


def main() -> int:
    args = parse_args()
    try:
        audit_result(args.protocol, args.manifest, args.freeze_receipt, args.result)
    except (base.AuditError, SuccessorError) as error:
        print(f"{SUCCESSOR_PROTOCOL_ID.upper()} AUDIT FAILED: {error}", file=sys.stderr)
        return 1
    print(f"{SUCCESSOR_PROTOCOL_ID} audit passed: {args.result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
