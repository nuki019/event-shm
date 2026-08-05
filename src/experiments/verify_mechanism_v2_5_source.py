"""Create a one-time v2.5 MD5+SHA-256 raw-byte source receipt.

The verifier never opens an archive or HDF5 payload.  It verifies frozen local
candidates first, preserves mismatches, and only downloads when the caller
explicitly supplies ``--allow-download`` to the isolated v2.5 directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from src.experiments.mechanism_v2_5_successor import (
    ROOT, PROTOCOL_ID, V25Error, load_v25_manifest, manifest_entry, resolve_within_root, sha256_file, verify_v25_freeze,
)


SOURCE_DATASET_IDS = {"ogw_cfrp_temperature_dam_d12", "ogw_cfrp_temperature_dam_d16", "morpho_fod7", "coqtel_corrosion"}
DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_5.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_5_data_manifest.json"
DEFAULT_FREEZE = ROOT / "protocols" / "mechanism_v2_5_freeze_receipt.json"
DEFAULT_DESTINATION = ROOT / "data" / "external" / "mechanism_v2_5"


class SourceVerificationError(RuntimeError):
    """Raised when a v2.5 source cannot be verified safely."""


def _hashes(path: Path) -> tuple[str, str]:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            md5.update(block)
            sha256.update(block)
    return md5.hexdigest(), sha256.hexdigest()


def _write_once(path: Path, payload: dict[str, Any], label: str) -> None:
    if path.exists():
        raise SourceVerificationError(f"refusing to overwrite {label}: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _specification(item: dict[str, Any]) -> tuple[str, int, str, str]:
    filename, size, checksum, url = item.get("filename"), item.get("size_bytes"), item.get("official_checksum"), item.get("download_url")
    if not isinstance(filename, str) or not isinstance(size, int) or not isinstance(checksum, dict) or not isinstance(url, str):
        raise SourceVerificationError("frozen file specification is incomplete")
    if checksum.get("algorithm") != "md5" or not isinstance(checksum.get("value"), str):
        raise SourceVerificationError(f"frozen file {filename} lacks an official MD5")
    return filename, size, str(checksum["value"]).lower(), url


def _candidate_paths(item: dict[str, Any]) -> list[Path]:
    candidates = item.get("local_candidate_paths")
    if not isinstance(candidates, list) or not candidates or not all(isinstance(value, str) for value in candidates):
        raise SourceVerificationError("frozen file specification lacks local candidate paths")
    return [resolve_within_root(value, "frozen local source candidate", must_exist=False) for value in candidates]


def _download(url: str, partial: Path) -> None:
    completed = subprocess.run(["curl.exe", "--location", "--fail", "--retry", "5", "--retry-delay", "5", "--output", str(partial), url], cwd=ROOT)
    if completed.returncode != 0:
        raise SourceVerificationError(f"curl failed with exit code {completed.returncode}")


def _download_fresh(item: dict[str, Any], destination: Path) -> tuple[Path, str, str]:
    filename, expected_size, expected_md5, url = _specification(item)
    destination.mkdir(parents=True, exist_ok=True)
    final = destination / filename
    partial = final.with_name(final.name + ".part")
    if final.exists() or partial.exists():
        raise SourceVerificationError(f"v2.5 download target already exists and will not be overwritten: {final}")
    _download(url, partial)
    if not partial.is_file() or partial.stat().st_size != expected_size:
        raise SourceVerificationError(f"downloaded {filename} does not have its frozen byte size")
    md5, sha256 = _hashes(partial)
    if md5 != expected_md5:
        raise SourceVerificationError(f"downloaded {filename} MD5 differs from its frozen official checksum")
    partial.replace(final)
    return final, md5, sha256


def _verify_file(item: dict[str, Any], destination: Path, allow_download: bool) -> dict[str, Any]:
    filename, expected_size, expected_md5, _ = _specification(item)
    mismatches: list[dict[str, Any]] = []
    for candidate in _candidate_paths(item):
        if not candidate.is_file():
            continue
        md5, sha256 = _hashes(candidate)
        if candidate.stat().st_size == expected_size and md5 == expected_md5:
            return {
                "filename": filename, "path": str(candidate.relative_to(ROOT)), "size_bytes": int(candidate.stat().st_size),
                "md5": md5, "sha256": sha256, "md5_verified_before_waveform_access": True,
                "source_origin": "preexisting_local_candidate_reverified_for_v2_5", "local_mismatches_preserved": mismatches,
            }
        mismatches.append({
            "path": str(candidate.relative_to(ROOT)), "size_bytes": int(candidate.stat().st_size), "actual_md5": md5,
            "actual_sha256": sha256, "expected_size_bytes": expected_size, "expected_md5": expected_md5,
            "preserved_without_overwrite": True,
        })
    if not allow_download:
        state = "no local candidate was present" if not mismatches else "local MD5/size mismatch was preserved"
        raise SourceVerificationError(f"{filename}: {state}; use --allow-download only for the isolated v2.5 destination")
    downloaded, md5, sha256 = _download_fresh(item, destination)
    return {
        "filename": filename, "path": str(downloaded.relative_to(ROOT)), "size_bytes": int(downloaded.stat().st_size),
        "md5": md5, "sha256": sha256, "md5_verified_before_waveform_access": True,
        "source_origin": "fresh_v2_5_download_after_absent_or_mismatched_local_candidate", "local_mismatches_preserved": mismatches,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=sorted(SOURCE_DATASET_IDS), required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--failure-receipt", type=Path)
    parser.add_argument("--allow-download", action="store_true")
    return parser.parse_args()


def _failure(dataset_id: str, error: Exception) -> dict[str, Any]:
    return {
        "receipt_id": "mechanism-v2.5-source-verification-failure-v1",
        "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "protocol_id": PROTOCOL_ID, "dataset_id": dataset_id, "waveform_access_permitted": False,
        "status": "failed_before_waveform_access", "reason": str(error),
        "attempted_command_policy": "raw-byte MD5+SHA-256 verification only; no archive or HDF5 payload was opened",
    }


def main() -> int:
    args = parse_args()
    dataset_id = str(args.dataset)
    try:
        protocol_path = resolve_within_root(args.protocol, "v2.5 protocol")
        manifest_path = resolve_within_root(args.manifest, "v2.5 manifest")
        freeze_path = resolve_within_root(args.freeze_receipt, "v2.5 freeze receipt")
        destination = resolve_within_root(args.destination, "v2.5 independent destination", must_exist=False)
        receipt_path = resolve_within_root(args.receipt, "v2.5 source receipt", must_exist=False)
        failure_path = resolve_within_root(args.failure_receipt, "v2.5 source failure receipt", must_exist=False) if args.failure_receipt else None
        if receipt_path.exists():
            raise SourceVerificationError(f"refusing to overwrite v2.5 source receipt: {receipt_path}")
        protocol = verify_v25_freeze(protocol_path, manifest_path, freeze_path)
        manifest, _ = load_v25_manifest(manifest_path)
        entry = manifest_entry(manifest, dataset_id)
        files = entry.get("files")
        if not isinstance(files, list) or not files or not all(isinstance(item, dict) for item in files):
            raise SourceVerificationError("frozen source entry lacks a valid files list")
        verified = [_verify_file(item, destination, bool(args.allow_download)) for item in files]
        _write_once(receipt_path, {
            "receipt_id": "mechanism-v2.5-source-verification-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": protocol["protocol_id"], "protocol_sha256": sha256_file(protocol_path),
            "data_manifest_sha256": sha256_file(manifest_path), "freeze_receipt_sha256": sha256_file(freeze_path),
            "dataset_id": dataset_id, "data_role": entry["role"], "waveform_access_permitted": True,
            "archive_and_content_hashes": verified, "raw_byte_hashing_only": True,
            "archive_or_hdf5_payload_opened": False, "historical_receipts_reused_for_authorization": False,
        }, "v2.5 source receipt")
    except (SourceVerificationError, V25Error, OSError) as error:
        if 'failure_path' in locals() and failure_path is not None:
            try:
                _write_once(failure_path, _failure(dataset_id, error), "v2.5 source failure receipt")
            except (SourceVerificationError, OSError) as receipt_error:
                print(f"MECHANISM-V2.5 SOURCE FAILURE RECEIPT FAILED: {receipt_error}", file=sys.stderr)
        print(f"MECHANISM-V2.5 SOURCE VERIFICATION FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
