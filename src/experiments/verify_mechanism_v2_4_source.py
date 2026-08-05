"""Create one immutable v2.4 MD5+SHA-256 source receipt.

The verifier hashes raw file bytes only.  It prefers the frozen local
candidate paths, never opens an archive or HDF5 payload, and refuses to
overwrite any receipt.  A mismatched local artifact is preserved; an explicit
``--allow-download`` may retrieve a fresh copy only below the independent
``data/external/mechanism_v2_4`` namespace.
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

from src.experiments.mechanism_v2_4_successor import (
    ROOT,
    PROTOCOL_ID,
    V24Error,
    load_json,
    load_v24_manifest,
    manifest_entry,
    resolve_within_root,
    sha256_file,
    verify_v24_freeze,
)


SOURCE_DATASET_IDS = {
    "ogw_cfrp_temperature_dam_d12",
    "ogw_cfrp_temperature_dam_d16",
    "morpho_fod7",
    "coqtel_corrosion",
}
DEFAULT_PROTOCOL = ROOT / "protocols" / "mechanism_v2_4.json"
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_4_data_manifest.json"
DEFAULT_FREEZE_RECEIPT = ROOT / "protocols" / "mechanism_v2_4_freeze_receipt.json"
DEFAULT_DESTINATION = ROOT / "data" / "external" / "mechanism_v2_4"


class SourceVerificationError(RuntimeError):
    """Raised when a v2.4 source cannot be safely verified."""


def _hashes(path: Path) -> tuple[str, str]:
    """Return MD5 and SHA-256 from one raw-byte pass."""

    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            md5.update(block)
            sha256.update(block)
    return md5.hexdigest(), sha256.hexdigest()


def _write_json_once(path: Path, payload: dict[str, Any], label: str) -> None:
    if path.exists():
        raise SourceVerificationError(f"refusing to overwrite {label}: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _files(entry: dict[str, Any]) -> list[dict[str, Any]]:
    files = entry.get("files")
    if not isinstance(files, list) or not files:
        raise SourceVerificationError("frozen source entry lacks a non-empty files list")
    output = [item for item in files if isinstance(item, dict)]
    if len(output) != len(files):
        raise SourceVerificationError("frozen source entry has a malformed file specification")
    return output


def _specification(file_spec: dict[str, Any]) -> tuple[str, int, str, str]:
    filename = file_spec.get("filename")
    size = file_spec.get("size_bytes")
    checksum = file_spec.get("official_checksum")
    url = file_spec.get("download_url")
    if not isinstance(filename, str) or not isinstance(size, int) or not isinstance(checksum, dict) or not isinstance(url, str):
        raise SourceVerificationError("frozen file specification is incomplete")
    if checksum.get("algorithm") != "md5" or not isinstance(checksum.get("value"), str):
        raise SourceVerificationError(f"frozen file {filename} lacks an official MD5")
    return filename, size, str(checksum["value"]).lower(), url


def _candidate_paths(file_spec: dict[str, Any]) -> list[Path]:
    candidates = file_spec.get("local_candidate_paths")
    if not isinstance(candidates, list) or not candidates or not all(isinstance(item, str) for item in candidates):
        raise SourceVerificationError("frozen file specification lacks local candidate paths")
    return [resolve_within_root(item, "frozen local source candidate", must_exist=False) for item in candidates]


def _download(url: str, partial_path: Path) -> None:
    command = ["curl.exe", "--location", "--fail", "--retry", "5", "--retry-delay", "5", "--output", str(partial_path), url]
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode != 0:
        raise SourceVerificationError(f"curl failed with exit code {completed.returncode}")


def _fresh_download(file_spec: dict[str, Any], destination: Path) -> tuple[Path, dict[str, Any]]:
    filename, expected_size, expected_md5, url = _specification(file_spec)
    destination.mkdir(parents=True, exist_ok=True)
    final = destination / filename
    if final.exists():
        raise SourceVerificationError(f"independent v2.4 destination already exists and will not be overwritten: {final}")
    partial = final.with_name(final.name + ".part")
    if partial.exists():
        raise SourceVerificationError(f"independent v2.4 partial transfer already exists and will not be overwritten: {partial}")
    _download(url, partial)
    if not partial.is_file() or partial.stat().st_size != expected_size:
        raise SourceVerificationError(f"downloaded {filename} does not have its frozen byte size")
    actual_md5, actual_sha256 = _hashes(partial)
    if actual_md5 != expected_md5:
        raise SourceVerificationError(f"downloaded {filename} MD5 differs from the frozen official checksum")
    partial.replace(final)
    return final, {
        "source_origin": "fresh_v2_4_download_after_absent_or_mismatched_local_candidate",
        "local_mismatches_preserved": [],
        "md5": actual_md5,
        "sha256": actual_sha256,
    }


def _verify_file(file_spec: dict[str, Any], destination: Path, allow_download: bool) -> dict[str, Any]:
    filename, expected_size, expected_md5, _ = _specification(file_spec)
    mismatches: list[dict[str, Any]] = []
    for candidate in _candidate_paths(file_spec):
        if not candidate.is_file():
            continue
        actual_md5, actual_sha256 = _hashes(candidate)
        if candidate.stat().st_size == expected_size and actual_md5 == expected_md5:
            return {
                "filename": filename,
                "path": str(candidate.relative_to(ROOT)),
                "size_bytes": int(candidate.stat().st_size),
                "md5": actual_md5,
                "sha256": actual_sha256,
                "md5_verified_before_waveform_access": True,
                "source_origin": "preexisting_local_candidate_reverified_for_v2_4",
                "local_mismatches_preserved": mismatches,
            }
        mismatches.append(
            {
                "path": str(candidate.relative_to(ROOT)),
                "size_bytes": int(candidate.stat().st_size),
                "actual_md5": actual_md5,
                "actual_sha256": actual_sha256,
                "expected_size_bytes": expected_size,
                "expected_md5": expected_md5,
                "preserved_without_overwrite": True,
            }
        )
    if not allow_download:
        detail = "no local candidate was present" if not mismatches else "local MD5/size mismatch was preserved"
        raise SourceVerificationError(f"{filename}: {detail}; pass --allow-download only to retrieve into the independent v2.4 destination")
    downloaded, details = _fresh_download(file_spec, destination)
    details["local_mismatches_preserved"] = mismatches
    return {
        "filename": filename,
        "path": str(downloaded.relative_to(ROOT)),
        "size_bytes": int(downloaded.stat().st_size),
        "md5": details["md5"],
        "sha256": details["sha256"],
        "md5_verified_before_waveform_access": True,
        "source_origin": details["source_origin"],
        "local_mismatches_preserved": details["local_mismatches_preserved"],
    }


def _failure_payload(args: argparse.Namespace, dataset_id: str, error: Exception) -> dict[str, Any]:
    return {
        "receipt_id": "mechanism-v2.4-source-verification-failure-v1",
        "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "protocol_id": PROTOCOL_ID,
        "dataset_id": dataset_id,
        "waveform_access_permitted": False,
        "status": "failed_before_waveform_access",
        "reason": str(error),
        "attempted_command_policy": "raw-byte MD5+SHA-256 verification only; no archive or HDF5 payload was opened",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=sorted(SOURCE_DATASET_IDS), required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--failure-receipt", type=Path)
    parser.add_argument("--allow-download", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_id = str(args.dataset)
    try:
        args.protocol = resolve_within_root(args.protocol, "mechanism-v2.4 protocol")
        args.manifest = resolve_within_root(args.manifest, "mechanism-v2.4 data manifest")
        args.freeze_receipt = resolve_within_root(args.freeze_receipt, "mechanism-v2.4 freeze receipt")
        args.destination = resolve_within_root(args.destination, "mechanism-v2.4 independent destination", must_exist=False)
        args.receipt = resolve_within_root(args.receipt, "mechanism-v2.4 source receipt", must_exist=False)
        if args.failure_receipt is not None:
            args.failure_receipt = resolve_within_root(args.failure_receipt, "mechanism-v2.4 source failure receipt", must_exist=False)
        protocol = verify_v24_freeze(args.protocol, args.manifest, args.freeze_receipt)
        manifest, _ = load_v24_manifest(args.manifest)
        entry = manifest_entry(manifest, dataset_id)
        files = [_verify_file(spec, args.destination, bool(args.allow_download)) for spec in _files(entry)]
        receipt = {
            "receipt_id": "mechanism-v2.4-source-verification-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": sha256_file(args.protocol),
            "data_manifest_sha256": sha256_file(args.manifest),
            "freeze_receipt_sha256": sha256_file(args.freeze_receipt),
            "dataset_id": dataset_id,
            "data_role": entry["role"],
            "waveform_access_permitted": True,
            "archive_and_content_hashes": files,
            "raw_byte_hashing_only": True,
            "archive_or_hdf5_payload_opened": False,
            "historical_receipts_reused_for_authorization": False,
        }
        _write_json_once(args.receipt, receipt, "v2.4 source receipt")
    except (SourceVerificationError, V24Error, OSError) as error:
        if getattr(args, "failure_receipt", None) is not None:
            try:
                _write_json_once(args.failure_receipt, _failure_payload(args, dataset_id, error), "v2.4 source failure receipt")
            except (SourceVerificationError, OSError) as receipt_error:
                print(f"MECHANISM-V2.4 SOURCE FAILURE RECEIPT FAILED: {receipt_error}", file=sys.stderr)
        print(f"MECHANISM-V2.4 SOURCE VERIFICATION FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
