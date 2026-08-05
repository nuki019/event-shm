"""One-shot OGW D12/D16 confirmation wrapper for mechanism-v2.5.

The frozen E7 representation and direct-ZIP reader are retained, while every
v2.5 receipt, output, and cache has a new namespace.  D04/D24 never appear in
this entry point.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments import e9_mechanism_v2_ogw as base
from src.experiments import mechanism_v2_5_successor as v25


DEFAULT_PROTOCOL = v25.ROOT / "protocols" / "mechanism_v2_5.json"
DEFAULT_MANIFEST = v25.ROOT / "protocols" / "mechanism_v2_5_data_manifest.json"
DEFAULT_FREEZE = v25.ROOT / "protocols" / "mechanism_v2_5_freeze_receipt.json"
DEFAULT_OUTPUTS = {"D12": v25.ROOT / "results" / "mechanism_v2_5_ogw_d12_confirmation.json", "D16": v25.ROOT / "results" / "mechanism_v2_5_ogw_d16_confirmation.json"}
MIN_AVAILABLE_MEMORY_BYTES = 8 * 1024**3


class MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong), ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong), ("total_page_file", ctypes.c_ulonglong), ("avail_page_file", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong), ("avail_extended_virtual", ctypes.c_ulonglong)]


def available_memory_bytes() -> int:
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise base.ConfirmationError("unable to query available physical memory for the v2.5 E9 memory gate")
    return int(status.avail_phys)


def _validate_receipt(path: Path, dataset_id: str, protocol_path: Path, manifest_path: Path, freeze_path: Path) -> None:
    receipt = v25.load_json(path)
    if receipt.get("protocol_id") != v25.PROTOCOL_ID or receipt.get("dataset_id") != dataset_id or receipt.get("waveform_access_permitted") is not True:
        raise base.ConfirmationError("v2.5 source receipt has the wrong dataset, protocol, or access state")
    expected = {"protocol_sha256": v25.sha256_file(protocol_path), "data_manifest_sha256": v25.sha256_file(manifest_path), "freeze_receipt_sha256": v25.sha256_file(freeze_path)}
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise base.ConfirmationError("v2.5 source receipt is not bound to the current frozen protocol")


def _code_revision() -> str:
    tracked = [
        v25.ROOT / "src" / "experiments" / "e9_mechanism_v2_5_ogw.py",
        v25.ROOT / "src" / "experiments" / "mechanism_v2_5_successor.py",
        v25.ROOT / "src" / "experiments" / "e9_mechanism_v2_ogw.py",
        v25.ROOT / "src" / "methods" / "mechanism_v2.py",
        v25.ROOT / "src" / "methods" / "strict_codecs.py",
    ]
    digest = hashlib.sha256()
    for path in tracked:
        digest.update(path.relative_to(v25.ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return f"mechanism_v2_5_ogw_source_sha256:{digest.hexdigest()}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", choices=("D12", "D16"), required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--calibration-receipt", type=Path, default=v25.ROOT / "results" / "mechanism_v2_5_ogw_udam_calibration_binding.json")
    parser.add_argument("--confirmation-receipt", type=Path, required=True)
    parser.add_argument("--strict-cache-dir", type=Path, default=v25.ROOT / "data" / "interim" / "strict_codec_v1")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    condition = args.condition.upper()
    args.cache_dir = args.cache_dir or (v25.ROOT / "data" / "interim" / f"mechanism_v2_5_ogw_{condition.lower()}")
    args.output = args.output or DEFAULT_OUTPUTS[condition]
    args.force_cache = False  # Required by the historical base runner; never exposed in v2.5.
    return args


def run(args: argparse.Namespace) -> dict:
    protocol_path = v25.resolve_within_root(args.protocol, "v2.5 E9 protocol")
    manifest_path = v25.resolve_within_root(args.manifest, "v2.5 E9 manifest")
    freeze_path = v25.resolve_within_root(args.freeze_receipt, "v2.5 E9 freeze receipt")
    calibration_path = v25.resolve_within_root(args.calibration_receipt, "v2.5 E9 calibration receipt")
    confirmation_path = v25.resolve_within_root(args.confirmation_receipt, "v2.5 E9 confirmation receipt")
    cache_dir = v25.resolve_within_root(args.cache_dir, "v2.5 E9 cache directory", must_exist=False)
    output = v25.resolve_within_root(args.output, "v2.5 E9 output", must_exist=False)
    if cache_dir.exists() or output.exists():
        raise base.ConfirmationError("v2.5 E9 cache/output namespace already exists; refusing a rerun")
    if available_memory_bytes() < MIN_AVAILABLE_MEMORY_BYTES:
        raise base.ConfirmationError("v2.5 E9 requires at least 8 GiB available physical memory before direct ZIP access")
    protocol = v25.verify_v25_freeze(protocol_path, manifest_path, freeze_path)
    manifest, _ = v25.load_v25_manifest(manifest_path)
    condition = str(args.condition).upper()
    dataset_id = f"ogw_cfrp_temperature_dam_{condition.lower()}"
    if v25.manifest_entry(manifest, dataset_id).get("role") != "same_plate_blind_confirmation":
        raise base.ConfirmationError("v2.5 E9 condition is not a frozen blind confirmation source")
    _validate_receipt(calibration_path, "ogw_cfrp_temperature_udam", protocol_path, manifest_path, freeze_path)
    _validate_receipt(confirmation_path, dataset_id, protocol_path, manifest_path, freeze_path)
    original_loader, original_revision = base._load_json, base._git_revision
    was_supported = v25.PROTOCOL_ID in base.SUPPORTED_PROTOCOL_IDS
    base.SUPPORTED_PROTOCOL_IDS.add(v25.PROTOCOL_ID)

    def loader(path: Path) -> dict:
        resolved = Path(path).resolve()
        if resolved == protocol_path:
            return protocol
        if resolved == manifest_path:
            return manifest
        return original_loader(path)

    base._load_json, base._git_revision = loader, _code_revision
    args.protocol, args.manifest, args.freeze_receipt = protocol_path, manifest_path, freeze_path
    args.calibration_receipt, args.confirmation_receipt, args.cache_dir, args.output = calibration_path, confirmation_path, cache_dir, output
    try:
        result = base.run(args)
        # Base runner owns heavy evaluation. The wrapper appends v2.5-only
        # bindings before returning; any interruption leaves a fail-closed,
        # occupied namespace rather than a rerunnable result.
        result["freeze_receipt_sha256"] = v25.sha256_file(freeze_path)
        result["result_schema_sha256"] = protocol["result_schema"]["sha256"]
        result["data"]["schema_gate"]["v2_5_wrapper"] = True
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        base._load_json, base._git_revision = original_loader, original_revision
        if not was_supported:
            base.SUPPORTED_PROTOCOL_IDS.discard(v25.PROTOCOL_ID)


def main() -> int:
    try:
        run(parse_args())
    except (base.ConfirmationError, v25.V25Error, OSError) as error:
        print(f"MECHANISM-V2.5 OGW CONFIRMATION FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
