"""Download a frozen mechanism-v2 source and verify it before waveform access.

This tool accepts only dataset entries already present in the frozen manifest.
It resumes a partial transfer when possible, checks the official MD5 before
renaming the final artifact, records SHA-256, and writes an access receipt.
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


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "protocols" / "mechanism_v2_data_manifest.json"
DEFAULT_FREEZE_RECEIPT = ROOT / "protocols" / "mechanism_v2_freeze_receipt.json"
DEFAULT_DESTINATION = ROOT / "data" / "external" / "mechanism_v2"


class DownloadError(RuntimeError):
    """Raised for frozen-source or checksum contract violations."""


def _resolve_within_workspace(path: Path, label: str) -> Path:
    """Resolve a CLI path and reject destinations outside the workspace."""

    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError as error:
        raise DownloadError(f"{label} must lie under the workspace root: {path}") from error
    return resolved


def _sha(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DownloadError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise DownloadError(f"{path} is not a JSON object")
    return value


def _find_dataset(manifest: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    entries = manifest.get("data_sets")
    if not isinstance(entries, list):
        raise DownloadError("manifest lacks data_sets")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("dataset_id") == dataset_id]
    if len(matches) != 1:
        raise DownloadError(f"dataset {dataset_id!r} is absent or duplicated")
    return matches[0]


def _files(entry: dict[str, Any]) -> list[dict[str, Any]]:
    official = entry.get("official")
    if not isinstance(official, dict):
        raise DownloadError("dataset has no official source metadata")
    files = official.get("files")
    if isinstance(files, list):
        return [item for item in files if isinstance(item, dict)]
    if all(key in official for key in ("archive_filename", "download_url", "size_bytes", "official_checksum")):
        return [
            {
                "filename": official["archive_filename"],
                "download_url": official["download_url"],
                "size_bytes": official["size_bytes"],
                "official_checksum": official["official_checksum"],
            }
        ]
    raise DownloadError("manifest source has no downloadable file list")


def _download(url: str, partial_path: Path) -> None:
    command = ["curl.exe", "--location", "--fail", "--retry", "5", "--retry-delay", "5", "--output", str(partial_path)]
    if partial_path.exists() and partial_path.stat().st_size:
        command.extend(["--continue-at", "-"])
    command.append(url)
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode != 0:
        raise DownloadError(f"curl failed with exit code {completed.returncode} for {url}")


def _verify_and_finalize(file_spec: dict[str, Any], destination: Path, dry_run: bool) -> dict[str, Any]:
    filename = file_spec.get("filename") or file_spec.get("archive_filename")
    url = file_spec.get("download_url")
    size = file_spec.get("size_bytes")
    checksum = file_spec.get("official_checksum")
    if not (isinstance(filename, str) and isinstance(url, str) and isinstance(size, int) and isinstance(checksum, dict)):
        raise DownloadError("manifest file entry is incomplete")
    if checksum.get("algorithm") != "md5" or not isinstance(checksum.get("value"), str):
        raise DownloadError(f"{filename} lacks an official MD5")
    final_path = destination / filename
    partial_path = final_path.with_name(final_path.name + ".part")
    if dry_run:
        return {
            "filename": filename,
            "path": str(final_path.relative_to(ROOT)),
            "expected_size_bytes": size,
            "expected_md5": checksum["value"],
            "dry_run": True,
        }
    destination.mkdir(parents=True, exist_ok=True)
    if final_path.exists():
        actual_md5 = _sha(final_path, "md5")
        if actual_md5 != checksum["value"]:
            raise DownloadError(f"existing final file MD5 differs from frozen source: {final_path}")
    else:
        _download(url, partial_path)
        if not partial_path.exists():
            raise DownloadError(f"curl did not create {partial_path}")
        if partial_path.stat().st_size != size:
            raise DownloadError(f"{filename} size is {partial_path.stat().st_size}, expected {size}")
        actual_md5 = _sha(partial_path, "md5")
        if actual_md5 != checksum["value"]:
            raise DownloadError(f"{filename} MD5 differs from frozen source")
        partial_path.replace(final_path)
    return {
        "filename": filename,
        "path": str(final_path.relative_to(ROOT)),
        "size_bytes": int(final_path.stat().st_size),
        "md5": checksum["value"],
        "sha256": _sha(final_path, "sha256"),
        "md5_verified_before_waveform_access": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="dataset_id from the frozen mechanism-v2 manifest")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        args.manifest = _resolve_within_workspace(args.manifest, "manifest")
        args.freeze_receipt = _resolve_within_workspace(args.freeze_receipt, "freeze receipt")
        args.destination = _resolve_within_workspace(args.destination, "destination")
        args.receipt = _resolve_within_workspace(args.receipt, "receipt")
        manifest = _load(args.manifest)
        freeze = _load(args.freeze_receipt)
        if freeze.get("data_manifest_sha256") != _sha(args.manifest, "sha256"):
            raise DownloadError("freeze receipt does not match the frozen data manifest")
        entry = _find_dataset(manifest, args.dataset)
        permitted_states = {
            "not_downloaded",
            "downloaded_integrity_only_no_waveform_arrays_opened",
            "downloaded_no_waveform_arrays_opened_pending_successor_verification",
        }
        if entry.get("access_state_at_freeze") not in permitted_states:
            raise DownloadError("this downloader only handles a frozen confirmation source before waveform-array access")
        files = [_verify_and_finalize(item, args.destination, args.dry_run) for item in _files(entry)]
        receipt = {
            "receipt_id": f"{freeze.get('protocol_id', 'mechanism-v2')}-download-verification-v1",
            "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "protocol_id": freeze.get("protocol_id", "mechanism-v2"),
            "protocol_sha256": freeze.get("protocol_sha256"),
            "data_manifest_sha256": freeze.get("data_manifest_sha256"),
            "dataset_id": entry["dataset_id"],
            "data_role": entry["role"],
            "waveform_access_permitted": not args.dry_run,
            "archive_and_content_hashes": files,
        }
        if args.receipt.exists():
            raise DownloadError(f"refusing to overwrite existing download receipt: {args.receipt}")
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    except DownloadError as error:
        print(f"MECHANISM-V2 DOWNLOAD FAILED: {error}", file=sys.stderr)
        return 1
    print(f"saved {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
