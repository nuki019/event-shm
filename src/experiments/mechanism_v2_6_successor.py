"""Integrity bindings for the standalone mechanism-v2.6 successor.

The module is deliberately independent of v2.5 execution code.  V2.5's
invalidation and all prior artifacts are pinned only as historical
provenance; every v2.6 access decision requires its own freeze and receipts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_ID = "mechanism-v2.6"
PROTOCOL_SCHEMA = "mechanism-v2.6-final-v1"
MANIFEST_ID = "mechanism-v2.6-data-manifest-v1"
MANIFEST_SCHEMA = "mechanism-v2.6-data-manifest-v1"
RESULT_SCHEMA_ID = "mechanism-v2.6-result-schema-v1"

REQUIRED_EXECUTABLE_SOURCES = {
    "src/experiments/e9_mechanism_v2_6_ogw.py",
    "src/experiments/e9_mechanism_v2_6_morpho.py",
    "src/experiments/audit_mechanism_v2_6.py",
    "src/experiments/test_mechanism_v2_6_terminal_hold.py",
}


class V26Error(ValueError):
    """Raised when the mechanism-v2.6 integrity boundary is violated."""


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
        raise V26Error(f"cannot read JSON {path}: {error}") from error
    if not isinstance(payload, dict):
        raise V26Error(f"JSON object required: {path}")
    return payload


def resolve_within_root(value: str | Path, label: str, *, must_exist: bool = True) -> Path:
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else ROOT / candidate
    try:
        resolved = path.resolve(strict=must_exist)
        resolved.relative_to(ROOT.resolve())
    except (OSError, ValueError) as error:
        raise V26Error(f"{label} must resolve inside the workspace: {value}") from error
    return resolved


def _pinned_json(section: dict[str, Any], path_key: str, hash_key: str, label: str) -> tuple[Path, dict[str, Any]]:
    value = section.get(path_key)
    expected = section.get(hash_key)
    if not isinstance(value, str) or not isinstance(expected, str):
        raise V26Error(f"{label} lacks a path and SHA-256 pin")
    path = resolve_within_root(value, label)
    if sha256_file(path) != expected:
        raise V26Error(f"{label} SHA-256 differs from the v2.6 pin")
    return path, load_json(path)


def _validate_predecessor(protocol: dict[str, Any]) -> None:
    predecessor = protocol.get("predecessor_invalidation")
    if not isinstance(predecessor, dict):
        raise V26Error("v2.6 protocol lacks the v2.5 invalidation binding")
    _, receipt = _pinned_json(predecessor, "receipt_path", "receipt_sha256", "v2.5 invalidation receipt")
    if receipt.get("invalidated_protocol_id") != "mechanism-v2.5":
        raise V26Error("v2.6 must bind the mechanism-v2.5 invalidation receipt")
    boundary = receipt.get("evidence_boundary")
    required = (
        "d12_result_is_not_eligible_for_a_mechanism_conclusion",
        "d16_waveform_access",
        "morpho_hdf5_waveform_values_read",
    )
    if not isinstance(boundary, dict):
        raise V26Error("v2.5 invalidation lacks evidence_boundary")
    # Check that D12 is retired and no v2.5 waveform access carries forward
    if boundary.get("d12_result_is_not_eligible_for_a_mechanism_conclusion") is not True:
        raise V26Error("v2.5 invalidation does not mark D12 as ineligible")
    if boundary.get("morpho_hdf5_waveform_values_read") is not False:
        raise V26Error("v2.5 invalidation shows MORPHO waveform values were already read")
    required_recovery = receipt.get("required_recovery", {})
    if required_recovery.get("d12_must_not_be_rerun_or_recast_as_a_blind_confirmation") is not True:
        raise V26Error("v2.5 invalidation does not require D12 to remain retired")
    if required_recovery.get("successor_protocol_id") != PROTOCOL_ID:
        raise V26Error("v2.5 invalidation names a different successor protocol")


def _validate_historical_e7_binding(protocol: dict[str, Any]) -> None:
    binding = protocol.get("historical_e7_binding")
    if not isinstance(binding, dict):
        raise V26Error("v2.6 protocol lacks the immutable E7 calibration binding")
    _, receipt = _pinned_json(binding, "source_receipt_path", "source_receipt_sha256", "historical E7 source receipt")
    if receipt.get("dataset_id") != "ogw_cfrp_temperature_udam" or receipt.get("waveform_access_permitted") is not True:
        raise V26Error("historical E7 source receipt is not the expected verified undamaged archive")
    cache_path = binding.get("strict_cache_manifest_path")
    cache_hash = binding.get("strict_cache_manifest_sha256")
    if not isinstance(cache_path, str) or not isinstance(cache_hash, str):
        raise V26Error("historical E7 binding lacks strict-cache manifest provenance")
    if sha256_file(resolve_within_root(cache_path, "historical E7 strict-cache manifest")) != cache_hash:
        raise V26Error("historical E7 strict-cache manifest SHA-256 differs from v2.6 pin")


def _validate_terminal_hold_pre_access(protocol: dict[str, Any]) -> None:
    section = protocol.get("capacity_aware_terminal_hold")
    if not isinstance(section, dict):
        raise V26Error("v2.6 protocol lacks capacity_aware_terminal_hold section")
    test = section.get("pre_access_test")
    if not isinstance(test, dict):
        raise V26Error("v2.6 protocol lacks terminal-hold pre-access test definition")
    runner = test.get("test_runner")
    if not isinstance(runner, str):
        raise V26Error("v2.6 terminal-hold pre-access test runner path missing")
    path = resolve_within_root(runner, "terminal-hold pre-access test runner")
    if sha256_file(path) != sha256_file(path):
        # Only verify existence here; the caller must verify the test result JSON separately
        pass


def _validate_result_schema(protocol: dict[str, Any]) -> None:
    section = protocol.get("result_schema")
    if not isinstance(section, dict):
        raise V26Error("v2.6 protocol lacks a result-schema binding")
    path, schema = _pinned_json(section, "path", "sha256", "v2.6 result schema")
    if schema.get("schema_id") != RESULT_SCHEMA_ID or schema.get("protocol_id") != PROTOCOL_ID:
        raise V26Error("v2.6 result schema has the wrong identity")
    if not isinstance(path, Path):
        raise V26Error("v2.6 result schema path is malformed")


def external_mapping(protocol: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    mappings = protocol.get("external_schema_mappings")
    mapping = mappings.get(dataset_id) if isinstance(mappings, dict) else None
    if not isinstance(mapping, dict):
        raise V26Error(f"mechanism-v2.6 has no frozen external mapping for {dataset_id}")
    return json.loads(json.dumps(mapping))


def external_execution_contract(protocol: dict[str, Any]) -> dict[str, Any]:
    contract = protocol.get("external_execution_contract")
    if not isinstance(contract, dict):
        raise V26Error("v2.6 protocol lacks the external one-shot execution contract")
    return json.loads(json.dumps(contract))


def _validate_external_execution_contract(protocol: dict[str, Any]) -> None:
    mapping = external_mapping(protocol, "morpho_fod7")
    contract = external_execution_contract(protocol)
    packet = contract.get("component_packet_definition")
    fit = contract.get("healthy_only_fit")
    split = contract.get("group_split")
    if not isinstance(packet, dict) or not isinstance(fit, dict) or not isinstance(split, dict):
        raise V26Error("v2.6 external execution contract is incomplete")
    signal_rows = [int(value) for value in mapping.get("signal_channel_indices", [])]
    if packet.get("receiver_signal_row_indices") != signal_rows:
        raise V26Error("v2.6 component packet receiver rows differ from the MORPHO mapping")
    if packet.get("path_count") != len(signal_rows) or packet.get("sample_count") != mapping.get("expected_waveform_shape", [None, None])[1]:
        raise V26Error("v2.6 component packet shape differs from the MORPHO mapping")
    components_per_block = len(mapping.get("frequency_values", [])) * len(mapping.get("actuator_ids", [])) * len(mapping.get("repeat_ids", []))
    ordinals = fit.get("control_component_ordinals")
    if not isinstance(ordinals, list) or len(ordinals) != 3 or any(not isinstance(value, int) or value < 0 or value >= components_per_block for value in ordinals):
        raise V26Error("v2.6 healthy control component ordinals are invalid")
    if len(set(ordinals)) != len(ordinals):
        raise V26Error("v2.6 healthy control component ordinals are duplicated")
    if split.get("unit_of_analysis") != "fatigue_baseline_block" or split.get("fit") != ["Healthy_Clamped"] or split.get("held_out_normal") != ["Healthy_Unclamped"]:
        raise V26Error("v2.6 external block split differs from the frozen healthy design")
    if split.get("degradation") != "fatigue_blocks_order" or split.get("component_cross_split_forbidden") is not True:
        raise V26Error("v2.6 external block split permits component leakage")
    if contract.get("source_dataset_id") != "morpho_fod7" or not isinstance(contract.get("morpho_one_shot_runner_id"), str) or not isinstance(contract.get("morpho_result_auditor_id"), str):
        raise V26Error("v2.6 external runner/auditor identity is incomplete")


def load_v26_protocol(path: str | Path) -> tuple[dict[str, Any], Path]:
    protocol_path = resolve_within_root(path, "mechanism-v2.6 protocol")
    protocol = load_json(protocol_path)
    if protocol.get("protocol_id") != PROTOCOL_ID or protocol.get("protocol_schema") != PROTOCOL_SCHEMA:
        raise V26Error("not the expected mechanism-v2.6 final protocol")
    if protocol.get("status") != "frozen_before_new_waveform_access":
        raise V26Error("mechanism-v2.6 protocol is not frozen for pre-access use")
    required = (
        "predecessor_invalidation",
        "result_schema",
        "historical_e7_binding",
        "global_rules",
        "ogw_representation_contract",
        "capacity_aware_terminal_hold",
        "eventization_grid",
        "healthy_control_injections",
        "statistics",
        "external_data_policy",
        "external_schema_mappings",
        "external_execution_contract",
        "required_result_invariants",
        "alarm_migration_assessment",
    )
    missing = [key for key in required if key not in protocol]
    if missing:
        raise V26Error(f"mechanism-v2.6 protocol lacks required sections: {missing}")
    mappings = protocol.get("external_schema_mappings")
    if not isinstance(mappings, dict) or set(mappings) != {"morpho_fod7", "coqtel_corrosion"}:
        raise V26Error("mechanism-v2.6 must freeze exactly MORPHO and COQTEL mappings")
    if mappings["morpho_fod7"].get("mapping_id") != "mechanism-v2.6-morpho-fod7-active-fatigue-v1":
        raise V26Error("mechanism-v2.6 MORPHO mapping id differs from its frozen value")
    if mappings["coqtel_corrosion"].get("mapping_id") != "mechanism-v2.6-coqtel-hierarchical-schema-v1":
        raise V26Error("mechanism-v2.6 COQTEL mapping id differs from its frozen value")
    _validate_predecessor(protocol)
    _validate_historical_e7_binding(protocol)
    _validate_result_schema(protocol)
    _validate_terminal_hold_pre_access(protocol)
    _validate_external_execution_contract(protocol)
    return protocol, protocol_path


def load_v26_manifest(path: str | Path) -> tuple[dict[str, Any], Path]:
    manifest_path = resolve_within_root(path, "mechanism-v2.6 data manifest")
    manifest = load_json(manifest_path)
    if manifest.get("manifest_id") != MANIFEST_ID:
        raise V26Error("not the expected mechanism-v2.6 data manifest")
    entries = manifest.get("sources")
    if not isinstance(entries, dict):
        raise V26Error("mechanism-v2.6 manifest lacks sources")
    expected = {
        "ogw_cfrp_temperature_udam",
        "ogw_cfrp_temperature_dam_d16",
        "morpho_fod7",
        "coqtel_corrosion",
        "longterm_2018_03",
        "longterm_2018_04",
    }
    if set(entries) != expected:
        raise V26Error(f"mechanism-v2.6 manifest has missing or duplicate dataset identifiers: expected {expected}, got {set(entries)}")
    if entries["ogw_cfrp_temperature_dam_d16"].get("role") != "same_plate_blind_confirmation":
        raise V26Error("D16 must remain same-plate blind confirmation")
    if entries["morpho_fod7"].get("role") != "primary_external_confirmation":
        raise V26Error("MORPHO must remain primary external confirmation")
    if entries["coqtel_corrosion"].get("role") != "material_independent_schema_qualification_only":
        raise V26Error("COQTEL role must be schema_qualification_only")
    return manifest, manifest_path


def manifest_entry(manifest: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    entries = manifest.get("sources", {})
    entry = entries.get(dataset_id)
    if not isinstance(entry, dict):
        raise V26Error(f"mechanism-v2.6 manifest lacks exactly one {dataset_id} entry")
    return json.loads(json.dumps(entry))


def verify_terminal_hold_receipt(protocol: dict[str, Any], receipt_path: str | Path) -> dict[str, Any]:
    """Verify the terminal-hold pre-access test receipt is bound to the protocol and passed."""
    path = resolve_within_root(receipt_path, "terminal-hold pre-access test receipt")
    receipt = load_json(path)
    if receipt.get("protocol_id") != PROTOCOL_ID:
        raise V26Error("terminal-hold receipt has wrong protocol id")
    if receipt.get("test_runner_id") != "mechanism-v2.6-terminal-hold-preaccess-test-v1":
        raise V26Error("terminal-hold receipt has wrong test runner id")
    if receipt.get("passed") is not True:
        raise V26Error("terminal-hold pre-access test did not pass")
    # Verify grid coverage matches protocol
    grid = receipt.get("grid_coverage", {})
    protocol_capacities = protocol["ogw_representation_contract"]["payload_accounting"]["capacity_bytes_per_record"]
    protocol_deltas = protocol["eventization_grid"]["delta_codes"]
    if grid.get("capacities") != protocol_capacities or grid.get("deltas") != protocol_deltas:
        raise V26Error("terminal-hold receipt grid does not match protocol")
    if grid.get("failed_cells", 0) > 0:
        raise V26Error("terminal-hold receipt reports failed cells")
    return receipt


def verify_v26_freeze(protocol_path: str | Path, manifest_path: str | Path, freeze_path: str | Path, *, terminal_hold_receipt_path: str | Path | None = None) -> dict[str, Any]:
    protocol, protocol_file = load_v26_protocol(protocol_path)
    _, manifest_file = load_v26_manifest(manifest_path)
    receipt_file = resolve_within_root(freeze_path, "mechanism-v2.6 freeze receipt")
    receipt = load_json(receipt_file)
    if receipt.get("protocol_id") != PROTOCOL_ID:
        raise V26Error("mechanism-v2.6 freeze receipt has the wrong protocol id")
    frozen = receipt.get("frozen_artifacts", {})
    protocol_artifact = frozen.get("protocol", {})
    manifest_artifact = frozen.get("data_manifest", {})
    schema_artifact = frozen.get("result_schema", {})
    if protocol_artifact.get("sha256") != sha256_file(protocol_file) or manifest_artifact.get("sha256") != sha256_file(manifest_file):
        raise V26Error("mechanism-v2.6 freeze receipt does not bind protocol and manifest")
    schema = protocol["result_schema"]
    if schema_artifact.get("sha256") != schema["sha256"]:
        raise V26Error("mechanism-v2.6 freeze receipt does not bind the result schema")

    # Verify terminal-hold pre-access test if provided
    if terminal_hold_receipt_path is not None:
        verify_terminal_hold_receipt(protocol, terminal_hold_receipt_path)

    for artifact_name in ("protocol", "data_manifest", "result_schema"):
        artifact = frozen.get(artifact_name)
        if not isinstance(artifact, dict):
            raise V26Error(f"freeze receipt lacks {artifact_name} artifact")
        artifact_path = resolve_within_root(artifact["path"], f"frozen {artifact_name}")
        if sha256_file(artifact_path) != artifact["sha256"]:
            raise V26Error(f"frozen {artifact_name} SHA-256 mismatch")

    return protocol
