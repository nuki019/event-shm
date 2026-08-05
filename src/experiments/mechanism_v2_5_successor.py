"""Integrity bindings for the standalone mechanism-v2.5 successor.

The module is deliberately independent of v2.4 execution code.  V2.4's
invalidation and no-value MORPHO discoveries are pinned only as historical
provenance; every v2.5 access decision requires its own freeze and receipts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_ID = "mechanism-v2.5"
PROTOCOL_SCHEMA = "mechanism-v2.5-final-v1"
MANIFEST_ID = "mechanism-v2.5-data-manifest-v1"
MANIFEST_SCHEMA = "mechanism-v2.5-data-manifest-v1"
RESULT_SCHEMA_ID = "mechanism-v2.5-result-schema-v1"

REQUIRED_EXECUTABLE_SOURCES = {
    "src/experiments/e9_mechanism_v2_5_ogw.py",
    "src/experiments/e9_mechanism_v2_5_morpho.py",
    "src/experiments/audit_mechanism_v2_5_ogw.py",
    "src/experiments/audit_mechanism_v2_5.py",
}


class V25Error(ValueError):
    """Raised when the mechanism-v2.5 integrity boundary is violated."""


def sha256_file(path: str | Path) -> str:
    """Hash raw bytes without interpreting their payload."""

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
        raise V25Error(f"cannot read JSON {path}: {error}") from error
    if not isinstance(payload, dict):
        raise V25Error(f"JSON object required: {path}")
    return payload


def resolve_within_root(value: str | Path, label: str, *, must_exist: bool = True) -> Path:
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else ROOT / candidate
    try:
        resolved = path.resolve(strict=must_exist)
        resolved.relative_to(ROOT.resolve())
    except (OSError, ValueError) as error:
        raise V25Error(f"{label} must resolve inside the workspace: {value}") from error
    return resolved


def _pinned_json(section: dict[str, Any], path_key: str, hash_key: str, label: str) -> tuple[Path, dict[str, Any]]:
    value = section.get(path_key)
    expected = section.get(hash_key)
    if not isinstance(value, str) or not isinstance(expected, str):
        raise V25Error(f"{label} lacks a path and SHA-256 pin")
    path = resolve_within_root(value, label)
    if sha256_file(path) != expected:
        raise V25Error(f"{label} SHA-256 differs from the v2.5 pin")
    return path, load_json(path)


def _validate_predecessor(protocol: dict[str, Any]) -> None:
    predecessor = protocol.get("predecessor_invalidation")
    if not isinstance(predecessor, dict):
        raise V25Error("v2.5 protocol lacks the v2.4 invalidation binding")
    _, receipt = _pinned_json(predecessor, "receipt_path", "receipt_sha256", "v2.4 invalidation receipt")
    if receipt.get("invalidated_protocol_id") != "mechanism-v2.4":
        raise V25Error("v2.5 must bind the mechanism-v2.4 invalidation receipt")
    boundary = receipt.get("evidence_boundary")
    required_false = (
        "morpho_hdf5_waveform_values_read",
        "coqtel_hdf5_waveform_values_read",
        "any_signal_metric_computed",
        "any_label_read_for_scoring",
        "any_event_cache_written",
        "any_e9_confirmation_result_written",
        "any_mechanism_result_audit_written",
    )
    if not isinstance(boundary, dict) or any(boundary.get(key) is not False for key in required_false):
        raise V25Error("v2.4 invalidation does not preserve the required pre-score boundary")


def _validate_historical_e7_binding(protocol: dict[str, Any]) -> None:
    binding = protocol.get("historical_e7_binding")
    if not isinstance(binding, dict):
        raise V25Error("v2.5 protocol lacks the immutable E7 calibration binding")
    _, receipt = _pinned_json(binding, "source_receipt_path", "source_receipt_sha256", "historical E7 source receipt")
    if receipt.get("dataset_id") != "ogw_cfrp_temperature_udam" or receipt.get("waveform_access_permitted") is not True:
        raise V25Error("historical E7 source receipt is not the expected verified undamaged archive")
    cache_path = binding.get("strict_cache_manifest_path")
    cache_hash = binding.get("strict_cache_manifest_sha256")
    if not isinstance(cache_path, str) or not isinstance(cache_hash, str):
        raise V25Error("historical E7 binding lacks strict-cache manifest provenance")
    if sha256_file(resolve_within_root(cache_path, "historical E7 strict-cache manifest")) != cache_hash:
        raise V25Error("historical E7 strict-cache manifest SHA-256 differs from v2.5 pin")


def _validate_morpho_provenance(protocol: dict[str, Any]) -> None:
    provenance = protocol.get("morpho_mapping_provenance")
    if not isinstance(provenance, dict):
        raise V25Error("v2.5 protocol lacks MORPHO mapping provenance")
    structural_section = provenance.get("structural_discovery")
    semantic_section = provenance.get("semantic_discovery")
    if not isinstance(structural_section, dict) or not isinstance(semantic_section, dict):
        raise V25Error("v2.5 MORPHO provenance is incomplete")
    structural_path, structural = _pinned_json(structural_section, "result_path", "result_sha256", "MORPHO structural discovery")
    semantic_path, semantic = _pinned_json(semantic_section, "result_path", "result_sha256", "MORPHO semantic discovery")
    if structural.get("protocol_id") != "mechanism-v2.4-morpho-metadata-discovery":
        raise V25Error("MORPHO structural discovery has the wrong historical protocol id")
    if semantic.get("protocol_id") != "mechanism-v2.4-morpho-semantic-discovery":
        raise V25Error("MORPHO semantic discovery has the wrong historical protocol id")
    structural_access = structural.get("access_receipt")
    semantic_access = semantic.get("access_receipt")
    if not isinstance(structural_access, dict) or any(
        structural_access.get(key) is not False
        for key in ("waveform_values_read", "metadata_values_read", "attribute_values_read", "labels_read")
    ):
        raise V25Error("MORPHO structural discovery crossed its no-value boundary")
    if not isinstance(semantic_access, dict) or any(
        semantic_access.get(key) is not False
        for key in ("hdf5_opened", "waveform_values_read", "metadata_values_read", "labels_read_for_scoring", "signal_metrics_computed")
    ):
        raise V25Error("MORPHO semantic discovery crossed its document-only boundary")
    if semantic.get("structural_discovery_result_sha256") != sha256_file(structural_path):
        raise V25Error("MORPHO semantic discovery is not bound to structural discovery")
    if not isinstance(semantic_path, Path):
        raise V25Error("MORPHO semantic discovery path is malformed")


def _validate_result_schema(protocol: dict[str, Any]) -> None:
    section = protocol.get("result_schema")
    if not isinstance(section, dict):
        raise V25Error("v2.5 protocol lacks a result-schema binding")
    path, schema = _pinned_json(section, "path", "sha256", "v2.5 result schema")
    if schema.get("schema_id") != RESULT_SCHEMA_ID or schema.get("protocol_id") != PROTOCOL_ID:
        raise V25Error("v2.5 result schema has the wrong identity")
    if not isinstance(path, Path):
        raise V25Error("v2.5 result schema path is malformed")


def external_mapping(protocol: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    mappings = protocol.get("external_schema_mappings")
    mapping = mappings.get(dataset_id) if isinstance(mappings, dict) else None
    if not isinstance(mapping, dict):
        raise V25Error(f"mechanism-v2.5 has no frozen external mapping for {dataset_id}")
    return json.loads(json.dumps(mapping))


def external_execution_contract(protocol: dict[str, Any]) -> dict[str, Any]:
    contract = protocol.get("external_execution_contract")
    if not isinstance(contract, dict):
        raise V25Error("v2.5 protocol lacks the external one-shot execution contract")
    return json.loads(json.dumps(contract))


def _validate_external_execution_contract(protocol: dict[str, Any]) -> None:
    mapping = external_mapping(protocol, "morpho_fod7")
    contract = external_execution_contract(protocol)
    packet = contract.get("component_packet_definition")
    fit = contract.get("healthy_only_fit")
    split = contract.get("group_split")
    if not isinstance(packet, dict) or not isinstance(fit, dict) or not isinstance(split, dict):
        raise V25Error("v2.5 external execution contract is incomplete")
    signal_rows = [int(value) for value in mapping.get("signal_channel_indices", [])]
    if packet.get("receiver_signal_row_indices") != signal_rows:
        raise V25Error("v2.5 component packet receiver rows differ from the MORPHO mapping")
    if packet.get("path_count") != len(signal_rows) or packet.get("sample_count") != mapping.get("expected_waveform_shape", [None, None])[1]:
        raise V25Error("v2.5 component packet shape differs from the MORPHO mapping")
    components_per_block = len(mapping.get("frequency_values", [])) * len(mapping.get("actuator_ids", [])) * len(mapping.get("repeat_ids", []))
    ordinals = fit.get("control_component_ordinals")
    if not isinstance(ordinals, list) or len(ordinals) != 3 or any(not isinstance(value, int) or value < 0 or value >= components_per_block for value in ordinals):
        raise V25Error("v2.5 healthy control component ordinals are invalid")
    if len(set(ordinals)) != len(ordinals):
        raise V25Error("v2.5 healthy control component ordinals are duplicated")
    if split.get("unit_of_analysis") != "fatigue_baseline_block" or split.get("fit") != ["Healthy_Clamped"] or split.get("held_out_normal") != ["Healthy_Unclamped"]:
        raise V25Error("v2.5 external block split differs from the frozen healthy design")
    if split.get("degradation") != "fatigue_blocks_order" or split.get("component_cross_split_forbidden") is not True:
        raise V25Error("v2.5 external block split permits component leakage")
    if contract.get("source_dataset_id") != "morpho_fod7" or not isinstance(contract.get("morpho_one_shot_runner_id"), str) or not isinstance(contract.get("morpho_result_auditor_id"), str):
        raise V25Error("v2.5 external runner/auditor identity is incomplete")


def load_v25_protocol(path: str | Path) -> tuple[dict[str, Any], Path]:
    protocol_path = resolve_within_root(path, "mechanism-v2.5 protocol")
    protocol = load_json(protocol_path)
    if protocol.get("protocol_id") != PROTOCOL_ID or protocol.get("protocol_schema") != PROTOCOL_SCHEMA:
        raise V25Error("not the expected mechanism-v2.5 final protocol")
    if protocol.get("status") != "frozen_before_new_waveform_access":
        raise V25Error("mechanism-v2.5 protocol is not frozen for pre-access use")
    required = (
        "predecessor_invalidation",
        "result_schema",
        "morpho_mapping_provenance",
        "historical_e7_binding",
        "global_rules",
        "ogw_representation_contract",
        "eventization_grid",
        "healthy_control_injections",
        "statistics",
        "external_data_policy",
        "external_schema_mappings",
        "external_execution_contract",
        "required_result_invariants",
    )
    missing = [key for key in required if key not in protocol]
    if missing:
        raise V25Error(f"mechanism-v2.5 protocol lacks required sections: {missing}")
    mappings = protocol.get("external_schema_mappings")
    if not isinstance(mappings, dict) or set(mappings) != {"morpho_fod7", "coqtel_corrosion"}:
        raise V25Error("mechanism-v2.5 must freeze exactly MORPHO and COQTEL mappings")
    if mappings["morpho_fod7"].get("mapping_id") != "mechanism-v2.5-morpho-fod7-active-fatigue-v1":
        raise V25Error("mechanism-v2.5 MORPHO mapping id differs from its frozen value")
    if mappings["coqtel_corrosion"].get("mapping_id") != "mechanism-v2.5-coqtel-hierarchical-schema-v1":
        raise V25Error("mechanism-v2.5 COQTEL mapping id differs from its frozen value")
    _validate_predecessor(protocol)
    _validate_historical_e7_binding(protocol)
    _validate_morpho_provenance(protocol)
    _validate_result_schema(protocol)
    _validate_external_execution_contract(protocol)
    return protocol, protocol_path


def load_v25_manifest(path: str | Path) -> tuple[dict[str, Any], Path]:
    manifest_path = resolve_within_root(path, "mechanism-v2.5 data manifest")
    manifest = load_json(manifest_path)
    if manifest.get("manifest_id") != MANIFEST_ID or manifest.get("manifest_schema") != MANIFEST_SCHEMA:
        raise V25Error("not the expected mechanism-v2.5 data manifest")
    entries = manifest.get("data_sets")
    if not isinstance(entries, list):
        raise V25Error("mechanism-v2.5 manifest lacks data_sets")
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
        raise V25Error("mechanism-v2.5 manifest has missing or duplicate dataset identifiers")
    roles = {entry["dataset_id"]: entry.get("role") for entry in entries if isinstance(entry, dict)}
    if roles["ogw_cfrp_temperature_dam_d04"] != "mechanism_discovery_only" or roles["ogw_cfrp_temperature_dam_d24"] != "mechanism_discovery_only":
        raise V25Error("D04/D24 must remain discovery-only in mechanism-v2.5")
    if any(roles[key] != "same_plate_blind_confirmation" for key in ("ogw_cfrp_temperature_dam_d12", "ogw_cfrp_temperature_dam_d16")):
        raise V25Error("D12/D16 must remain same-plate blind confirmations")
    if roles["morpho_fod7"] != "primary_external_confirmation" or roles["coqtel_corrosion"] != "material_independent_confirmation":
        raise V25Error("mechanism-v2.5 external roles differ from the frozen plan")
    return manifest, manifest_path


def manifest_entry(manifest: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    entries = manifest.get("data_sets")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("dataset_id") == dataset_id] if isinstance(entries, list) else []
    if len(matches) != 1:
        raise V25Error(f"mechanism-v2.5 manifest lacks exactly one {dataset_id} entry")
    return json.loads(json.dumps(matches[0]))


def verify_v25_freeze(protocol_path: str | Path, manifest_path: str | Path, freeze_path: str | Path) -> dict[str, Any]:
    protocol, protocol_file = load_v25_protocol(protocol_path)
    _, manifest_file = load_v25_manifest(manifest_path)
    receipt_file = resolve_within_root(freeze_path, "mechanism-v2.5 freeze receipt")
    receipt = load_json(receipt_file)
    if receipt.get("protocol_id") != PROTOCOL_ID:
        raise V25Error("mechanism-v2.5 freeze receipt has the wrong protocol id")
    if receipt.get("protocol_sha256") != sha256_file(protocol_file) or receipt.get("data_manifest_sha256") != sha256_file(manifest_file):
        raise V25Error("mechanism-v2.5 freeze receipt does not bind protocol and manifest")
    schema = protocol["result_schema"]
    if receipt.get("result_schema_sha256") != schema["sha256"]:
        raise V25Error("mechanism-v2.5 freeze receipt does not bind the result schema")
    source_hashes = receipt.get("frozen_source_sha256")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise V25Error("mechanism-v2.5 freeze receipt lacks frozen source hashes")
    if not REQUIRED_EXECUTABLE_SOURCES <= set(source_hashes):
        raise V25Error("mechanism-v2.5 freeze omits a required runner or auditor")
    for relative, expected in source_hashes.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise V25Error("mechanism-v2.5 freeze source hash entry is malformed")
        if sha256_file(resolve_within_root(relative, "mechanism-v2.5 frozen source")) != expected:
            raise V25Error(f"mechanism-v2.5 frozen source differs: {relative}")
    mappings = protocol["external_schema_mappings"]
    if receipt.get("frozen_morpho_mapping_sha256") != json_hash(mappings["morpho_fod7"]):
        raise V25Error("mechanism-v2.5 freeze receipt does not bind the MORPHO mapping")
    if receipt.get("frozen_coqtel_mapping_sha256") != json_hash(mappings["coqtel_corrosion"]):
        raise V25Error("mechanism-v2.5 freeze receipt does not bind the COQTEL mapping")
    if receipt.get("frozen_external_execution_contract_sha256") != json_hash(protocol["external_execution_contract"]):
        raise V25Error("mechanism-v2.5 freeze receipt does not bind the external runner contract")
    if receipt.get("new_waveform_access_before_receipt") is not False:
        raise V25Error("mechanism-v2.5 freeze receipt does not preserve the pre-access boundary")
    return protocol
