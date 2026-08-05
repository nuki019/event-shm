"""One-shot OGW D12/D16 confirmation entry point for mechanism-v2.4.

This wrapper preserves the fixed E7 representation and direct-ZIP access used
by the validated base runner, but adds v2.4's standalone freeze verification,
fresh receipt namespace, isolated cache namespace, and memory gate.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments import e9_mechanism_v2_ogw as base
from src.experiments import mechanism_v2_4_successor as v24


DEFAULT_PROTOCOL = v24.ROOT / "protocols" / "mechanism_v2_4.json"
DEFAULT_MANIFEST = v24.ROOT / "protocols" / "mechanism_v2_4_data_manifest.json"
DEFAULT_FREEZE_RECEIPT = v24.ROOT / "protocols" / "mechanism_v2_4_freeze_receipt.json"
DEFAULT_OUTPUTS = {
    "D12": v24.ROOT / "results" / "mechanism_v2_4_ogw_d12_confirmation.json",
    "D16": v24.ROOT / "results" / "mechanism_v2_4_ogw_d16_confirmation.json",
}
MIN_AVAILABLE_MEMORY_BYTES = 8 * 1024**3


class MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ulong),
        ("memory_load", ctypes.c_ulong),
        ("total_phys", ctypes.c_ulonglong),
        ("avail_phys", ctypes.c_ulonglong),
        ("total_page_file", ctypes.c_ulonglong),
        ("avail_page_file", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong),
        ("avail_virtual", ctypes.c_ulonglong),
        ("avail_extended_virtual", ctypes.c_ulonglong),
    ]


def available_memory_bytes() -> int:
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise base.ConfirmationError("unable to query available physical memory for the v2.4 E9 memory gate")
    return int(status.avail_phys)


def _validate_source_receipt(path: Path, dataset_id: str, protocol_path: Path, manifest_path: Path) -> None:
    receipt = v24.load_json(path)
    if receipt.get("protocol_id") != v24.PROTOCOL_ID or receipt.get("dataset_id") != dataset_id:
        raise base.ConfirmationError("v2.4 E9 source receipt has the wrong dataset or protocol")
    if receipt.get("protocol_sha256") != v24.sha256_file(protocol_path) or receipt.get("data_manifest_sha256") != v24.sha256_file(manifest_path):
        raise base.ConfirmationError("v2.4 E9 source receipt is not bound to the current frozen protocol and manifest")


def _v24_code_revision() -> str:
    tracked = [
        v24.ROOT / "src" / "experiments" / "e9_mechanism_v2_4_ogw.py",
        v24.ROOT / "src" / "experiments" / "mechanism_v2_4_successor.py",
        v24.ROOT / "src" / "experiments" / "e9_mechanism_v2_ogw.py",
        v24.ROOT / "src" / "methods" / "mechanism_v2.py",
        v24.ROOT / "src" / "methods" / "strict_codecs.py",
    ]
    digest = hashlib.sha256()
    for path in tracked:
        digest.update(path.relative_to(v24.ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return f"mechanism_v2_4_source_sha256:{digest.hexdigest()}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", choices=("D12", "D16"), required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument(
        "--calibration-receipt",
        type=Path,
        default=v24.ROOT / "results" / "mechanism_v2_4_ogw_udam_calibration_binding.json",
    )
    parser.add_argument("--confirmation-receipt", type=Path, required=True)
    parser.add_argument("--strict-cache-dir", type=Path, default=v24.ROOT / "data" / "interim" / "strict_codec_v1")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    condition = args.condition.upper()
    if args.cache_dir is None:
        args.cache_dir = v24.ROOT / "data" / "interim" / f"mechanism_v2_4_ogw_{condition.lower()}"
    if args.output is None:
        args.output = DEFAULT_OUTPUTS[condition]
    return args


def run(args: argparse.Namespace) -> dict:
    protocol_path = v24.resolve_within_root(args.protocol, "v2.4 E9 protocol")
    manifest_path = v24.resolve_within_root(args.manifest, "v2.4 E9 manifest")
    freeze_path = v24.resolve_within_root(args.freeze_receipt, "v2.4 E9 freeze receipt")
    calibration_path = v24.resolve_within_root(args.calibration_receipt, "v2.4 E9 calibration receipt")
    confirmation_path = v24.resolve_within_root(args.confirmation_receipt, "v2.4 E9 confirmation receipt")
    cache_dir = v24.resolve_within_root(args.cache_dir, "v2.4 E9 cache directory", must_exist=False)
    output = v24.resolve_within_root(args.output, "v2.4 E9 output", must_exist=False)
    if cache_dir.exists():
        raise base.ConfirmationError(f"v2.4 E9 cache directory already exists; refusing a rerun: {cache_dir}")
    if output.exists():
        raise base.ConfirmationError(f"v2.4 E9 output already exists; refusing a rerun: {output}")
    if available_memory_bytes() < MIN_AVAILABLE_MEMORY_BYTES:
        raise base.ConfirmationError("v2.4 E9 requires at least 8 GiB available physical memory before direct ZIP access")
    protocol = v24.verify_v24_freeze(protocol_path, manifest_path, freeze_path)
    manifest, _ = v24.load_v24_manifest(manifest_path)
    condition = str(args.condition).upper()
    dataset_id = f"ogw_cfrp_temperature_dam_{condition.lower()}"
    if v24.manifest_entry(manifest, dataset_id).get("role") != "same_plate_blind_confirmation":
        raise base.ConfirmationError("v2.4 E9 condition is not a frozen blind confirmation source")
    _validate_source_receipt(calibration_path, "ogw_cfrp_temperature_udam", protocol_path, manifest_path)
    _validate_source_receipt(confirmation_path, dataset_id, protocol_path, manifest_path)
    original_loader = base._load_json
    original_revision = base._git_revision
    base.SUPPORTED_PROTOCOL_IDS.add(v24.PROTOCOL_ID)

    def v24_loader(path: Path) -> dict:
        resolved = Path(path).resolve()
        if resolved == protocol_path:
            return protocol
        if resolved == manifest_path:
            return manifest
        return original_loader(path)

    base._load_json = v24_loader
    base._git_revision = _v24_code_revision
    args.protocol = protocol_path
    args.manifest = manifest_path
    args.freeze_receipt = freeze_path
    args.calibration_receipt = calibration_path
    args.confirmation_receipt = confirmation_path
    args.cache_dir = cache_dir
    args.output = output
    try:
        return base.run(args)
    finally:
        base._load_json = original_loader
        base._git_revision = original_revision


def main() -> int:
    try:
        run(parse_args())
    except (base.ConfirmationError, v24.V24Error) as error:
        print(f"MECHANISM-V2.4 OGW CONFIRMATION FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
