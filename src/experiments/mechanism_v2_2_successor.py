"""Resolution and validation helpers for the immutable mechanism-v2.2 successor.

The v2.2 JSON files are intentionally small overlays.  They inherit every
unchanged evaluation setting from the immutable v2.1 files while pinning their
SHA-256 digests.  This avoids silently editing a frozen predecessor and makes
the one metadata-driven schema extension explicit.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SUCCESSOR_PROTOCOL_ID = "mechanism-v2.2"
OVERLAY_SCHEMA = "mechanism-v2-successor-overlay-v1"


class SuccessorError(ValueError):
    """Raised when a successor overlay cannot be resolved reproducibly."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_within_root(value: str | Path, label: str) -> Path:
    path = Path(value)
    candidate = path if path.is_absolute() else ROOT / path
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(ROOT.resolve())
    except (OSError, ValueError) as error:
        raise SuccessorError(f"{label} must resolve inside the workspace: {value}") from error
    return resolved


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SuccessorError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(payload, dict):
        raise SuccessorError(f"JSON object required: {path}")
    return payload


def _pinned_base(overlay: dict[str, Any], key: str, hash_key: str, label: str) -> Path:
    inherited = overlay.get("inherits")
    if not isinstance(inherited, dict):
        raise SuccessorError(f"{label} overlay lacks inherits")
    value = inherited.get(key)
    expected_hash = inherited.get(hash_key)
    if not isinstance(value, str) or not isinstance(expected_hash, str):
        raise SuccessorError(f"{label} overlay has no pinned inherited {key}")
    path = resolve_within_root(value, f"inherited {label}")
    if sha256_file(path) != expected_hash:
        raise SuccessorError(f"inherited {label} SHA-256 differs from the overlay pin")
    return path


def load_successor_protocol(
    path: str | Path, expected_protocol_id: str = SUCCESSOR_PROTOCOL_ID
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the resolved v2.2 protocol and its immutable overlay payload."""

    overlay_path = resolve_within_root(path, "successor protocol")
    overlay = load_json(overlay_path)
    if overlay.get("protocol_id") != expected_protocol_id or overlay.get("protocol_schema") != OVERLAY_SCHEMA:
        raise SuccessorError(f"not a {expected_protocol_id} protocol overlay")
    if overlay.get("status") != "frozen_before_new_waveform_access":
        raise SuccessorError("successor protocol is not frozen")
    base_path = _pinned_base(overlay, "protocol_path", "protocol_sha256", "protocol")
    base = load_json(base_path)
    if base.get("protocol_id") != "mechanism-v2.1":
        raise SuccessorError("v2.2 must inherit the immutable mechanism-v2.1 protocol")
    overrides = overlay.get("successor_overrides")
    if not isinstance(overrides, dict):
        raise SuccessorError("successor protocol lacks successor_overrides")
    resolved = copy.deepcopy(base)
    for key, value in overrides.items():
        resolved[key] = copy.deepcopy(value)
    resolved["protocol_id"] = expected_protocol_id
    resolved["status"] = overlay["status"]
    resolved["successor_overlay"] = {
        "path": str(overlay_path.relative_to(ROOT)),
        "sha256": sha256_file(overlay_path),
        "base_path": str(base_path.relative_to(ROOT)),
        "base_sha256": sha256_file(base_path),
    }
    return resolved, overlay


def load_successor_manifest(path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the resolved v2.2 data manifest and its immutable overlay payload."""

    overlay_path = resolve_within_root(path, "successor data manifest")
    overlay = load_json(overlay_path)
    if overlay.get("manifest_schema") != OVERLAY_SCHEMA:
        raise SuccessorError("not a mechanism-v2.2 data-manifest overlay")
    base_path = _pinned_base(overlay, "manifest_path", "manifest_sha256", "data manifest")
    base = load_json(base_path)
    if not isinstance(base.get("data_sets"), list):
        raise SuccessorError("inherited data manifest lacks data_sets")
    overrides = overlay.get("data_set_overrides")
    if not isinstance(overrides, dict):
        raise SuccessorError("successor data manifest lacks data_set_overrides")
    resolved = copy.deepcopy(base)
    for entry in resolved["data_sets"]:
        if not isinstance(entry, dict):
            raise SuccessorError("inherited data manifest contains a non-object entry")
        update = overrides.get(entry.get("dataset_id"))
        if update is not None:
            if not isinstance(update, dict):
                raise SuccessorError("data_set_overrides must contain objects")
            entry.update(copy.deepcopy(update))
    resolved["manifest_id"] = overlay.get("manifest_id")
    resolved["successor_overlay"] = {
        "path": str(overlay_path.relative_to(ROOT)),
        "sha256": sha256_file(overlay_path),
        "base_path": str(base_path.relative_to(ROOT)),
        "base_sha256": sha256_file(base_path),
    }
    return resolved, overlay


def verify_successor_freeze(
    protocol_path: str | Path,
    manifest_path: str | Path,
    freeze_path: str | Path,
    expected_protocol_id: str = SUCCESSOR_PROTOCOL_ID,
) -> dict[str, Any]:
    """Check that a v2.2 freeze receipt binds the exact overlay files."""

    protocol_file = resolve_within_root(protocol_path, "successor protocol")
    manifest_file = resolve_within_root(manifest_path, "successor data manifest")
    freeze_file = resolve_within_root(freeze_path, "successor freeze receipt")
    resolved_protocol, _ = load_successor_protocol(protocol_file, expected_protocol_id)
    load_successor_manifest(manifest_file)
    freeze = load_json(freeze_file)
    if freeze.get("protocol_id") != expected_protocol_id:
        raise SuccessorError(f"freeze receipt protocol id differs from {expected_protocol_id}")
    if freeze.get("protocol_sha256") != sha256_file(protocol_file):
        raise SuccessorError("freeze receipt protocol SHA-256 differs from v2.2 overlay")
    if freeze.get("data_manifest_sha256") != sha256_file(manifest_file):
        raise SuccessorError("freeze receipt manifest SHA-256 differs from v2.2 overlay")
    source_hashes = freeze.get("frozen_source_sha256")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise SuccessorError("freeze receipt lacks frozen source hashes")
    for relative, expected in source_hashes.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise SuccessorError("freeze receipt has malformed source hash entry")
        path = resolve_within_root(relative, "frozen source")
        if sha256_file(path) != expected:
            raise SuccessorError(f"frozen source SHA-256 differs: {relative}")
    return resolved_protocol


def manifest_entry(manifest: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    entries = manifest.get("data_sets")
    if not isinstance(entries, list):
        raise SuccessorError("resolved manifest lacks data_sets")
    found = [entry for entry in entries if isinstance(entry, dict) and entry.get("dataset_id") == dataset_id]
    if len(found) != 1:
        raise SuccessorError(f"resolved manifest lacks exactly one {dataset_id} entry")
    return found[0]


def external_mapping(protocol: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    mappings = protocol.get("external_schema_mappings")
    if not isinstance(mappings, dict):
        raise SuccessorError("successor protocol lacks external_schema_mappings")
    mapping = mappings.get(dataset_id)
    if not isinstance(mapping, dict):
        raise SuccessorError(f"successor protocol has no mapping for {dataset_id}")
    return copy.deepcopy(mapping)
