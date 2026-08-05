"""Mechanism-v2.3 bindings for the tested generic successor-overlay resolver."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.experiments import mechanism_v2_2_successor as _core


ROOT = _core.ROOT
SUCCESSOR_PROTOCOL_ID = "mechanism-v2.3"
SuccessorError = _core.SuccessorError
sha256_file = _core.sha256_file
json_hash = _core.json_hash
resolve_within_root = _core.resolve_within_root
load_json = _core.load_json
manifest_entry = _core.manifest_entry
external_mapping = _core.external_mapping


def load_successor_protocol(path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    return _core.load_successor_protocol(path, SUCCESSOR_PROTOCOL_ID)


def load_successor_manifest(path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    return _core.load_successor_manifest(path)


def verify_successor_freeze(protocol_path: str | Path, manifest_path: str | Path, freeze_path: str | Path) -> dict[str, Any]:
    return _core.verify_successor_freeze(protocol_path, manifest_path, freeze_path, SUCCESSOR_PROTOCOL_ID)
