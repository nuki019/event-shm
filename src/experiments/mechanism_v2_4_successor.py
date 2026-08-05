"""Immutable bindings for the standalone mechanism-v2.4 protocol.

Version 2.4 deliberately does *not* inherit an earlier successor as an
authorization mechanism.  Earlier v2.1--v2.3 files are evidence history only.
This module verifies the new protocol, the fresh source manifest, and the
pre-access freeze receipt before any v2.4 source verifier, schema gate, or
one-shot runner can act.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_ID = "mechanism-v2.4"
PROTOCOL_SCHEMA = "mechanism-v2.4-final-v1"
MANIFEST_ID = "mechanism-v2.4-data-manifest-v1"
MANIFEST_SCHEMA = "mechanism-v2.4-data-manifest-v1"


class V24Error(ValueError):
    """Raised when a mechanism-v2.4 integrity boundary is violated."""


def sha256_file(path: str | Path) -> str:
    """Hash raw bytes without interpreting a source payload."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise V24Error(f"cannot read JSON {path}: {error}") from error
    if not isinstance(payload, dict):
        raise V24Error(f"JSON object required: {path}")
    return payload


def resolve_within_root(value: str | Path, label: str, *, must_exist: bool = True) -> Path:
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else ROOT / candidate
    try:
        resolved = path.resolve(strict=must_exist)
        resolved.relative_to(ROOT.resolve())
    except (OSError, ValueError) as error:
        raise V24Error(f"{label} must resolve inside the workspace: {value}") from error
    return resolved


def _pinned_json(section: dict[str, Any], path_key: str, hash_key: str, label: str) -> tuple[Path, dict[str, Any]]:
    value = section.get(path_key)
    expected = section.get(hash_key)
    if not isinstance(value, str) or not isinstance(expected, str):
        raise V24Error(f"{label} lacks a path and SHA-256 pin")
    path = resolve_within_root(value, label)
    if sha256_file(path) != expected:
        raise V24Error(f"{label} SHA-256 differs from the v2.4 pin")
    return path, load_json(path)


def _validate_predecessor(protocol: dict[str, Any]) -> None:
    predecessor = protocol["predecessor_invalidation"]
    if not isinstance(predecessor, dict):
        raise V24Error("v2.4 protocol lacks predecessor invalidation")
    _, receipt = _pinned_json(predecessor, "receipt_path", "receipt_sha256", "v2.3 invalidation receipt")
    if receipt.get("invalidated_protocol_id") != "mechanism-v2.3":
        raise V24Error("v2.4 must bind the mechanism-v2.3 invalidation receipt")
    boundary = receipt.get("evidence_boundary")
    required_false = (
        "morpho_hdf5_metadata_inspected",
        "morpho_hdf5_waveform_values_read",
        "any_signal_metric_computed",
        "any_label_read_for_scoring",
        "any_event_cache_written",
        "any_e9_confirmation_result_written",
    )
    if not isinstance(boundary, dict) or any(boundary.get(key) is not False for key in required_false):
        raise V24Error("v2.3 invalidation does not preserve the required pre-score boundary")


def _validate_morpho_mapping_provenance(protocol: dict[str, Any]) -> None:
    provenance = protocol["morpho_mapping_provenance"]
    if not isinstance(provenance, dict):
        raise V24Error("v2.4 protocol lacks MORPHO mapping provenance")
    structural_section = provenance.get("structural_discovery")
    semantic_section = provenance.get("semantic_discovery")
    if not isinstance(structural_section, dict) or not isinstance(semantic_section, dict):
        raise V24Error("v2.4 MORPHO mapping provenance is incomplete")

    structural_path, structural = _pinned_json(
        structural_section, "result_path", "result_sha256", "MORPHO structural discovery result"
    )
    if structural.get("protocol_id") != "mechanism-v2.4-morpho-metadata-discovery":
        raise V24Error("MORPHO structural provenance has the wrong protocol id")
    structural_access = structural.get("access_receipt")
    structural_false = (
        "waveform_values_read",
        "metadata_values_read",
        "attribute_values_read",
        "labels_read",
        "mapping_selected",
        "schema_eligibility_decided",
    )
    if not isinstance(structural_access, dict) or any(structural_access.get(key) is not False for key in structural_false):
        raise V24Error("MORPHO structural provenance is not a no-value/no-decision discovery")
    freeze_path, freeze = _pinned_json(
        structural_section, "freeze_receipt_path", "freeze_receipt_sha256", "MORPHO structural-discovery freeze receipt"
    )
    if freeze.get("protocol_sha256") != structural.get("protocol_sha256") or freeze.get("protocol_id") != structural.get("protocol_id"):
        raise V24Error("MORPHO structural discovery freeze does not bind its result protocol")
    if structural.get("freeze_receipt_sha256") != sha256_file(freeze_path):
        raise V24Error("MORPHO structural discovery result does not bind its freeze receipt")

    semantic_path, semantic = _pinned_json(
        semantic_section, "result_path", "result_sha256", "MORPHO semantic discovery result"
    )
    if semantic.get("protocol_id") != "mechanism-v2.4-morpho-semantic-discovery":
        raise V24Error("MORPHO semantic provenance has the wrong protocol id")
    semantic_access = semantic.get("access_receipt")
    semantic_false = (
        "hdf5_opened",
        "waveform_values_read",
        "metadata_values_read",
        "labels_read_for_scoring",
        "signal_metrics_computed",
        "mapping_selected",
        "schema_eligibility_decided",
    )
    if not isinstance(semantic_access, dict) or any(semantic_access.get(key) is not False for key in semantic_false):
        raise V24Error("MORPHO semantic provenance is not document-only/no-decision")
    semantic_freeze_path, semantic_freeze = _pinned_json(
        semantic_section, "freeze_receipt_path", "freeze_receipt_sha256", "MORPHO semantic-discovery freeze receipt"
    )
    if semantic_freeze.get("protocol_sha256") != semantic.get("protocol_sha256") or semantic_freeze.get("protocol_id") != semantic.get("protocol_id"):
        raise V24Error("MORPHO semantic discovery freeze does not bind its result protocol")
    if semantic.get("freeze_receipt_sha256") != sha256_file(semantic_freeze_path):
        raise V24Error("MORPHO semantic discovery result does not bind its freeze receipt")
    if semantic.get("structural_discovery_result_sha256") != sha256_file(structural_path):
        raise V24Error("MORPHO semantic discovery is not bound to the structural discovery result")

    mapping = external_mapping(protocol, "morpho_fod7")
    expected_blocks = list(mapping.get("baseline_blocks", [])) + list(mapping.get("fatigue_blocks_order", []))
    if not expected_blocks or len(expected_blocks) != len(set(expected_blocks)):
        raise V24Error("MORPHO mapping must have unique baseline and fatigue blocks")
    # The semantic-discovery receipt is deliberately the bridge between the
    # no-value structural inventory and the official document vocabulary.  Its
    # path-token summary, not the raw structural result, is the frozen source
    # for this final mapping check.
    summary = semantic.get("structural_path_summary")
    observed_tokens = summary.get("active_path_tokens") if isinstance(summary, dict) else None
    if not isinstance(observed_tokens, list) or set(expected_blocks) - set(observed_tokens):
        raise V24Error("MORPHO mapping declares a block absent from frozen structural discovery")
    if not isinstance(semantic_path, Path):  # Keeps static analyzers aware the pinned result was consumed.
        raise V24Error("MORPHO semantic discovery path is malformed")


def _validate_historical_e7_binding(protocol: dict[str, Any]) -> None:
    binding = protocol["historical_e7_binding"]
    if not isinstance(binding, dict):
        raise V24Error("v2.4 protocol lacks the immutable E7 calibration binding")
    receipt_path, receipt = _pinned_json(binding, "source_receipt_path", "source_receipt_sha256", "historical E7 source receipt")
    if receipt.get("dataset_id") != "ogw_cfrp_temperature_udam" or receipt.get("waveform_access_permitted") is not True:
        raise V24Error("historical E7 source receipt is not the expected verified undamaged archive")
    cache_value = binding.get("strict_cache_manifest_path")
    cache_hash = binding.get("strict_cache_manifest_sha256")
    if not isinstance(cache_value, str) or not isinstance(cache_hash, str):
        raise V24Error("historical E7 binding lacks strict-cache manifest provenance")
    cache_path = resolve_within_root(cache_value, "historical E7 strict-cache manifest")
    if sha256_file(cache_path) != cache_hash:
        raise V24Error("historical E7 strict-cache manifest SHA-256 differs from v2.4 pin")
    if not isinstance(receipt_path, Path):
        raise V24Error("historical E7 receipt path is malformed")


def load_v24_protocol(path: str | Path) -> tuple[dict[str, Any], Path]:
    protocol_path = resolve_within_root(path, "mechanism-v2.4 protocol")
    protocol = load_json(protocol_path)
    if protocol.get("protocol_id") != PROTOCOL_ID or protocol.get("protocol_schema") != PROTOCOL_SCHEMA:
        raise V24Error("not the expected mechanism-v2.4 final protocol")
    if protocol.get("status") != "frozen_before_new_waveform_access":
        raise V24Error("mechanism-v2.4 protocol is not frozen")
    required = (
        "predecessor_invalidation",
        "morpho_mapping_provenance",
        "historical_e7_binding",
        "global_rules",
        "ogw_representation_contract",
        "eventization_grid",
        "healthy_control_injections",
        "statistics",
        "external_data_policy",
        "external_schema_mappings",
        "required_result_invariants",
    )
    missing = [key for key in required if key not in protocol]
    if missing:
        raise V24Error(f"mechanism-v2.4 protocol lacks required sections: {missing}")
    mappings = protocol.get("external_schema_mappings")
    if not isinstance(mappings, dict) or set(mappings) != {"morpho_fod7", "coqtel_corrosion"}:
        raise V24Error("mechanism-v2.4 must freeze exactly MORPHO and COQTEL schema mappings")
    if mappings["morpho_fod7"].get("mapping_id") != "mechanism-v2.4-morpho-fod7-active-fatigue-v1":
        raise V24Error("mechanism-v2.4 MORPHO mapping id differs from the declared final mapping")
    if mappings["coqtel_corrosion"].get("mapping_id") != "mechanism-v2.4-coqtel-hierarchical-schema-v1":
        raise V24Error("mechanism-v2.4 COQTEL mapping id differs from the declared final mapping")
    _validate_predecessor(protocol)
    _validate_historical_e7_binding(protocol)
    _validate_morpho_mapping_provenance(protocol)
    return protocol, protocol_path


def load_v24_manifest(path: str | Path) -> tuple[dict[str, Any], Path]:
    manifest_path = resolve_within_root(path, "mechanism-v2.4 data manifest")
    manifest = load_json(manifest_path)
    if manifest.get("manifest_id") != MANIFEST_ID or manifest.get("manifest_schema") != MANIFEST_SCHEMA:
        raise V24Error("not the expected mechanism-v2.4 data manifest")
    entries = manifest.get("data_sets")
    if not isinstance(entries, list):
        raise V24Error("mechanism-v2.4 manifest lacks data_sets")
    identifiers = [entry.get("dataset_id") for entry in entries if isinstance(entry, dict)]
    expected = {
        "ogw_cfrp_temperature_udam",
        "ogw_cfrp_temperature_dam_d04",
        "ogw_cfrp_temperature_dam_d24",
        "ogw_cfrp_temperature_dam_d12",
        "ogw_cfrp_temperature_dam_d16",
        "morpho_fod7",
        "coqtel_corrosion",
        "copv_schema_failure_fallback",
    }
    if set(identifiers) != expected or len(identifiers) != len(expected):
        raise V24Error("mechanism-v2.4 manifest has missing or duplicate dataset identifiers")
    roles = {entry["dataset_id"]: entry.get("role") for entry in entries if isinstance(entry, dict)}
    if roles["ogw_cfrp_temperature_dam_d04"] != "mechanism_discovery_only" or roles["ogw_cfrp_temperature_dam_d24"] != "mechanism_discovery_only":
        raise V24Error("D04/D24 must remain discovery-only in mechanism-v2.4")
    if any(roles[key] != "same_plate_blind_confirmation" for key in ("ogw_cfrp_temperature_dam_d12", "ogw_cfrp_temperature_dam_d16")):
        raise V24Error("D12/D16 must remain same-plate blind confirmations")
    if roles["morpho_fod7"] != "primary_external_confirmation" or roles["coqtel_corrosion"] != "material_independent_confirmation":
        raise V24Error("mechanism-v2.4 external roles differ from the frozen plan")
    return manifest, manifest_path


def manifest_entry(manifest: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    entries = manifest.get("data_sets")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("dataset_id") == dataset_id] if isinstance(entries, list) else []
    if len(matches) != 1:
        raise V24Error(f"mechanism-v2.4 manifest lacks exactly one {dataset_id} entry")
    return dict(matches[0])


def external_mapping(protocol: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    mappings = protocol.get("external_schema_mappings")
    mapping = mappings.get(dataset_id) if isinstance(mappings, dict) else None
    if not isinstance(mapping, dict):
        raise V24Error(f"mechanism-v2.4 has no frozen external mapping for {dataset_id}")
    return json.loads(json.dumps(mapping))


def verify_v24_freeze(protocol_path: str | Path, manifest_path: str | Path, freeze_path: str | Path) -> dict[str, Any]:
    protocol, protocol_file = load_v24_protocol(protocol_path)
    _, manifest_file = load_v24_manifest(manifest_path)
    receipt_file = resolve_within_root(freeze_path, "mechanism-v2.4 freeze receipt")
    receipt = load_json(receipt_file)
    if receipt.get("protocol_id") != PROTOCOL_ID:
        raise V24Error("mechanism-v2.4 freeze receipt has the wrong protocol id")
    if receipt.get("protocol_sha256") != sha256_file(protocol_file) or receipt.get("data_manifest_sha256") != sha256_file(manifest_file):
        raise V24Error("mechanism-v2.4 freeze receipt does not bind protocol and manifest")
    source_hashes = receipt.get("frozen_source_sha256")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise V24Error("mechanism-v2.4 freeze receipt lacks frozen source hashes")
    for relative, expected in source_hashes.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise V24Error("mechanism-v2.4 freeze source hash entry is malformed")
        source = resolve_within_root(relative, "mechanism-v2.4 frozen source")
        if sha256_file(source) != expected:
            raise V24Error(f"mechanism-v2.4 frozen source differs: {relative}")
    mappings = protocol["external_schema_mappings"]
    if receipt.get("frozen_morpho_mapping_sha256") != json_hash(mappings["morpho_fod7"]):
        raise V24Error("mechanism-v2.4 freeze receipt does not bind the MORPHO mapping")
    if receipt.get("frozen_coqtel_mapping_sha256") != json_hash(mappings["coqtel_corrosion"]):
        raise V24Error("mechanism-v2.4 freeze receipt does not bind the COQTEL mapping")
    if receipt.get("new_waveform_access_before_receipt") is not False:
        raise V24Error("mechanism-v2.4 freeze receipt does not preserve the pre-access boundary")
    return protocol
