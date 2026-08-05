"""Invariants for the document-only MORPHO semantic discovery phase."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.experiments.mechanism_v2_4_metadata_discovery import ROOT, DiscoveryError, load_json, resolve_within_root, sha256_file


SEMANTIC_PROTOCOL_ID = "mechanism-v2.4-morpho-semantic-discovery"
SEMANTIC_SCHEMA = "mechanism-v2.4-semantic-discovery-v1"


def _pinned_file(section: dict[str, Any], path_key: str, sha_key: str, label: str) -> Path:
    value = section.get(path_key)
    expected = section.get(sha_key)
    if not isinstance(value, str) or not isinstance(expected, str):
        raise DiscoveryError(f"{label} lacks a pinned path and SHA-256")
    path = resolve_within_root(value, label)
    if sha256_file(path) != expected:
        raise DiscoveryError(f"{label} SHA-256 differs from its frozen pin")
    return path


def load_semantic_protocol(path: str | Path) -> tuple[dict[str, Any], Path]:
    protocol_path = resolve_within_root(path, "semantic-discovery protocol")
    protocol = load_json(protocol_path)
    if protocol.get("protocol_id") != SEMANTIC_PROTOCOL_ID or protocol.get("protocol_schema") != SEMANTIC_SCHEMA:
        raise DiscoveryError("not the expected v2.4 MORPHO semantic-discovery protocol")
    if protocol.get("status") != "frozen_before_morpho_document_semantic_access":
        raise DiscoveryError("semantic-discovery protocol is not frozen")
    for key in ("structural_discovery_provenance", "input_documents", "document_access_contract", "output_contract"):
        if not isinstance(protocol.get(key), dict):
            raise DiscoveryError(f"semantic-discovery protocol lacks {key}")
    return protocol, protocol_path


def validate_semantic_provenance(protocol: dict[str, Any]) -> tuple[Path, dict[str, Any], dict[str, Path]]:
    """Validate provenance and filesystem metadata without opening source docs."""

    structural = protocol["structural_discovery_provenance"]
    structural_path = _pinned_file(structural, "result_path", "result_sha256", "structural metadata-discovery result")
    structural_result = load_json(structural_path)
    if structural_result.get("protocol_id") != "mechanism-v2.4-morpho-metadata-discovery":
        raise DiscoveryError("semantic discovery is not bound to the v2.4 structural discovery result")
    access = structural_result.get("access_receipt")
    required_false = ("waveform_values_read", "metadata_values_read", "attribute_values_read", "labels_read", "mapping_selected", "schema_eligibility_decided")
    if not isinstance(access, dict) or any(access.get(key) is not False for key in required_false):
        raise DiscoveryError("structural discovery does not preserve the declared no-value/no-decision boundary")
    if structural.get("freeze_receipt_sha256") != structural_result.get("freeze_receipt_sha256"):
        raise DiscoveryError("semantic discovery does not bind the structural-discovery freeze receipt")

    documents = protocol["input_documents"]
    paths: dict[str, Path] = {}
    for key in ("readme_pdf", "reader_example"):
        specification = documents.get(key)
        if not isinstance(specification, dict):
            raise DiscoveryError(f"semantic discovery lacks {key} provenance")
        path = resolve_within_root(specification.get("path", ""), key)
        if not isinstance(specification.get("sha256"), str) or not isinstance(specification.get("size_bytes"), int):
            raise DiscoveryError(f"semantic discovery has incomplete {key} provenance")
        if path.stat().st_size != specification["size_bytes"]:
            raise DiscoveryError(f"{key} size differs from the frozen contract")
        paths[key] = path
    return structural_path, structural_result, paths


def verify_semantic_freeze(protocol_path: str | Path, freeze_path: str | Path) -> dict[str, Any]:
    protocol, resolved_protocol = load_semantic_protocol(protocol_path)
    freeze_file = resolve_within_root(freeze_path, "semantic-discovery freeze receipt")
    freeze = load_json(freeze_file)
    if freeze.get("protocol_id") != SEMANTIC_PROTOCOL_ID or freeze.get("protocol_sha256") != sha256_file(resolved_protocol):
        raise DiscoveryError("semantic-discovery freeze receipt does not bind the protocol")
    source_hashes = freeze.get("frozen_source_sha256")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise DiscoveryError("semantic-discovery freeze receipt lacks source hashes")
    for relative, expected in source_hashes.items():
        source = resolve_within_root(relative, "frozen semantic-discovery source")
        if not isinstance(expected, str) or sha256_file(source) != expected:
            raise DiscoveryError(f"semantic-discovery frozen source differs: {relative}")
    structural_path, structural_result, paths = validate_semantic_provenance(protocol)
    if freeze.get("structural_result_sha256") != sha256_file(structural_path):
        raise DiscoveryError("semantic-discovery freeze receipt does not bind structural provenance")
    if freeze.get("structural_freeze_receipt_sha256") != structural_result.get("freeze_receipt_sha256"):
        raise DiscoveryError("semantic-discovery freeze receipt does not bind structural freeze provenance")
    for key, path in paths.items():
        expected = protocol["input_documents"][key]["sha256"]
        if freeze.get("document_expected_sha256", {}).get(key) != expected or freeze.get("document_paths", {}).get(key) != str(path.relative_to(ROOT)):
            raise DiscoveryError(f"semantic-discovery freeze receipt does not bind {key}")
    return protocol
