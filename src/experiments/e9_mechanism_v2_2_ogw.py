"""One-shot OGW confirmation bound to the mechanism-v2.2 successor overlay."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments import e9_mechanism_v2_ogw as base
from src.experiments.mechanism_v2_2_successor import (
    ROOT,
    SUCCESSOR_PROTOCOL_ID,
    SuccessorError,
    load_successor_manifest,
    load_successor_protocol,
    resolve_within_root,
    verify_successor_freeze,
)


DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_2.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_2_data_manifest.json"
DEFAULT_FREEZE_RECEIPT = ROOT / "protocols" / "mechanism_v2_2_freeze_receipt.json"
DEFAULT_OUTPUTS = {
    "D12": ROOT / "results" / "mechanism_v2_2_ogw_d12_confirmation.json",
    "D16": ROOT / "results" / "mechanism_v2_2_ogw_d16_confirmation.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", choices=("D12", "D16"), required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--calibration-receipt", type=Path, default=ROOT / "results" / "mechanism_v2_ogw_udam_source_receipt.json")
    parser.add_argument("--confirmation-receipt", type=Path, required=True)
    parser.add_argument("--strict-cache-dir", type=Path, default=ROOT / "data" / "interim" / "strict_codec_v1")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--force-cache", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    condition = args.condition.upper()
    if args.cache_dir is None:
        args.cache_dir = ROOT / "data" / "interim" / f"mechanism_v2_2_ogw_{condition.lower()}"
    if args.output is None:
        args.output = DEFAULT_OUTPUTS[condition]
    return args


def run(args: argparse.Namespace) -> dict:
    protocol_path = resolve_within_root(args.protocol, "successor protocol")
    manifest_path = resolve_within_root(args.manifest, "successor data manifest")
    freeze_path = resolve_within_root(args.freeze_receipt, "successor freeze receipt")
    resolved_protocol, _ = load_successor_protocol(protocol_path)
    resolved_manifest, _ = load_successor_manifest(manifest_path)
    verify_successor_freeze(protocol_path, manifest_path, freeze_path)
    original_loader = base._load_json
    base.SUPPORTED_PROTOCOL_IDS.add(SUCCESSOR_PROTOCOL_ID)

    def successor_loader(path: Path) -> dict:
        resolved_path = Path(path).resolve()
        if resolved_path == protocol_path:
            return resolved_protocol
        if resolved_path == manifest_path:
            return resolved_manifest
        return original_loader(path)

    base._load_json = successor_loader
    try:
        return base.run(args)
    finally:
        base._load_json = original_loader


def main() -> int:
    try:
        run(parse_args())
    except (base.ConfirmationError, SuccessorError) as error:
        print(f"{SUCCESSOR_PROTOCOL_ID.upper()} OGW CONFIRMATION FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
