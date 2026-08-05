"""Shared invariants for the pre-v2.4 MORPHO structural discovery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DISCOVERY_PROTOCOL_ID = "mechanism-v2.4-morpho-metadata-discovery"
DISCOVERY_SCHEMA = "mechanism-v2.4-metadata-discovery-v1"


class DiscoveryError(ValueError):
    """Raised when the frozen structural-discovery contract is violated."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DiscoveryError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(payload, dict):
        raise DiscoveryError(f"JSON object required: {path}")
    return payload


def resolve_within_root(value: str | Path, label: str, *, must_exist: bool = True) -> Path:
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else ROOT / candidate
    try:
        resolved = path.resolve(strict=must_exist)
        resolved.relative_to(ROOT.resolve())
    except (OSError, ValueError) as error:
        raise DiscoveryError(f"{label} must resolve inside the workspace: {value}") from error
    return resolved


def load_discovery_protocol(path: str | Path) -> tuple[dict[str, Any], Path]:
    protocol_path = resolve_within_root(path, "metadata-discovery protocol")
    protocol = load_json(protocol_path)
    if protocol.get("protocol_id") != DISCOVERY_PROTOCOL_ID or protocol.get("protocol_schema") != DISCOVERY_SCHEMA:
        raise DiscoveryError("not the expected v2.4 MORPHO metadata-discovery protocol")
    if protocol.get("status") != "frozen_before_morpho_metadata_access":
        raise DiscoveryError("metadata-discovery protocol is not frozen")
    for key in ("predecessor_invalidation", "input_integrity_history", "metadata_access_contract", "output_contract"):
        if not isinstance(protocol.get(key), dict):
            raise DiscoveryError(f"metadata-discovery protocol lacks {key}")
    return protocol, protocol_path


def _pinned_file(section: dict[str, Any], path_key: str, sha_key: str, label: str) -> Path:
    value = section.get(path_key)
    expected = section.get(sha_key)
    if not isinstance(value, str) or not isinstance(expected, str):
        raise DiscoveryError(f"{label} lacks a pinned path and SHA-256")
    path = resolve_within_root(value, label)
    if sha256_file(path) != expected:
        raise DiscoveryError(f"{label} SHA-256 differs from its frozen pin")
    return path


def validate_predecessor_and_input(protocol: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    """Validate only JSON/filesystem provenance, never HDF5 contents."""

    predecessor = protocol["predecessor_invalidation"]
    invalidation_path = _pinned_file(predecessor, "receipt_path", "receipt_sha256", "v2.3 invalidation receipt")
    invalidation = load_json(invalidation_path)
    if invalidation.get("invalidated_protocol_id") != "mechanism-v2.3":
        raise DiscoveryError("metadata discovery must be rooted in the v2.3 invalidation")
    boundary = invalidation.get("evidence_boundary")
    if not isinstance(boundary, dict) or boundary.get("morpho_hdf5_metadata_inspected") is not False:
        raise DiscoveryError("v2.3 invalidation does not preserve the required pre-MORPHO-metadata boundary")

    history = protocol["input_integrity_history"]
    receipt_path = _pinned_file(history, "receipt_path", "receipt_sha256", "MORPHO integrity-history receipt")
    receipt = load_json(receipt_path)
    if receipt.get("dataset_id") != "morpho_fod7" or receipt.get("protocol_id") != "mechanism-v2.3":
        raise DiscoveryError("integrity-history receipt is not the invalidated v2.3 MORPHO source receipt")
    expected_h5 = history.get("hdf5")
    if not isinstance(expected_h5, dict):
        raise DiscoveryError("metadata-discovery protocol lacks HDF5 provenance")
    h5_path = resolve_within_root(expected_h5.get("path", ""), "MORPHO HDF5 source")
    if not h5_path.is_file():
        raise DiscoveryError("MORPHO HDF5 source is absent")
    if not isinstance(expected_h5.get("sha256"), str) or not isinstance(expected_h5.get("size_bytes"), int):
        raise DiscoveryError("MORPHO HDF5 provenance is incomplete")
    if h5_path.stat().st_size != expected_h5["size_bytes"]:
        raise DiscoveryError("MORPHO HDF5 size differs from the frozen metadata-discovery contract")
    entries = receipt.get("archive_and_content_hashes")
    matching = [entry for entry in entries if isinstance(entry, dict) and entry.get("filename") == h5_path.name]
    if len(matching) != 1 or matching[0].get("sha256") != expected_h5["sha256"]:
        raise DiscoveryError("MORPHO HDF5 provenance differs from the pinned integrity-history receipt")
    return invalidation_path, h5_path, receipt


def verify_discovery_freeze(protocol_path: str | Path, freeze_path: str | Path) -> dict[str, Any]:
    protocol, resolved_protocol = load_discovery_protocol(protocol_path)
    freeze_file = resolve_within_root(freeze_path, "metadata-discovery freeze receipt")
    freeze = load_json(freeze_file)
    if freeze.get("protocol_id") != DISCOVERY_PROTOCOL_ID:
        raise DiscoveryError("metadata-discovery freeze receipt has the wrong protocol id")
    if freeze.get("protocol_sha256") != sha256_file(resolved_protocol):
        raise DiscoveryError("metadata-discovery freeze receipt does not bind the protocol")
    source_hashes = freeze.get("frozen_source_sha256")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise DiscoveryError("metadata-discovery freeze receipt lacks source hashes")
    for relative, expected in source_hashes.items():
        source = resolve_within_root(relative, "frozen metadata-discovery source")
        if not isinstance(expected, str) or sha256_file(source) != expected:
            raise DiscoveryError(f"metadata-discovery frozen source differs: {relative}")
    invalidation_path, h5_path, receipt = validate_predecessor_and_input(protocol)
    if freeze.get("predecessor_invalidation_sha256") != sha256_file(invalidation_path):
        raise DiscoveryError("metadata-discovery freeze receipt does not bind the v2.3 invalidation")
    if freeze.get("integrity_history_receipt_sha256") != sha256_file(resolve_within_root(protocol["input_integrity_history"]["receipt_path"], "MORPHO integrity-history receipt")):
        raise DiscoveryError("metadata-discovery freeze receipt does not bind the MORPHO integrity history")
    if freeze.get("hdf5_path") != str(h5_path.relative_to(ROOT)) or freeze.get("hdf5_expected_sha256") != protocol["input_integrity_history"]["hdf5"]["sha256"]:
        raise DiscoveryError("metadata-discovery freeze receipt does not bind the declared HDF5 source")
    if receipt.get("waveform_access_permitted") is not True:
        raise DiscoveryError("integrity-history receipt does not contain the expected historical verification")
    return protocol
