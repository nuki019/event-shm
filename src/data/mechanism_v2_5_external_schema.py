"""Dataset-specific, metadata-only schema gates for mechanism-v2.5.

The validators consume only the v2.5 structural inventory.  They do not call
``Dataset.__getitem__`` or ``AttributeManager.__getitem__`` and therefore
cannot read a waveform, label, time value, or sampling-rate value.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np

from src.data.mechanism_hdf5_metadata_safe_v2_5 import SafeMetadataError, inspect_hdf5_structure_without_values
from src.experiments.mechanism_v2_5_successor import json_hash


class ExternalSchemaError(ValueError):
    """Raised when a frozen v2.5 external schema mapping is not satisfied."""


def _index(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects = inventory.get("objects")
    if not isinstance(objects, list):
        raise ExternalSchemaError("metadata inventory has no object list")
    indexed = {item.get("path"): item for item in objects if isinstance(item, dict) and isinstance(item.get("path"), str)}
    if not indexed:
        raise ExternalSchemaError("metadata inventory has no indexed HDF5 objects")
    return indexed


def _numeric_dataset(item: dict[str, Any], label: str) -> None:
    if item.get("kind") != "dataset":
        raise ExternalSchemaError(f"{label} is not a dataset")
    try:
        dtype = np.dtype(str(item.get("dtype")))
    except TypeError as error:
        raise ExternalSchemaError(f"{label} lacks a numeric dtype") from error
    if dtype.kind not in {"i", "u", "f"}:
        raise ExternalSchemaError(f"{label} is not numeric")


def _require_group_attribute(indexed: dict[str, dict[str, Any]], path: str, attribute: str, label: str) -> None:
    item = indexed.get(path)
    if item is None or item.get("kind") != "group":
        raise ExternalSchemaError(f"{label} group is absent: {path}")
    if attribute not in item.get("attributes", {}):
        raise ExternalSchemaError(f"{label} lacks required attribute name {attribute!r}: {path}")


def _require(mapping: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise ExternalSchemaError(f"{label} mapping lacks required fields: {missing}")


def validate_morpho_fod7_inventory(inventory: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    """Validate the frozen MORPHO Active/fatigue mapping without values."""

    _require(
        mapping,
        (
            "mapping_id", "active_root", "waveform_dataset_path_regex", "expected_waveform_shape", "sample_axis",
            "time_channel_axis", "time_channel_index", "signal_channel_indices", "frequency_values", "actuator_ids",
            "repeat_ids", "baseline_blocks", "fatigue_blocks_order", "excluded_active_blocks", "block_status_attribute",
            "sampling_rate_attribute", "monitoring_group_definition", "repeat_split_rule",
        ),
        "MORPHO",
    )
    indexed = _index(inventory)
    root = str(mapping["active_root"])
    if indexed.get(root, {}).get("kind") != "group":
        raise ExternalSchemaError("MORPHO active root is absent")
    try:
        pattern = re.compile(str(mapping["waveform_dataset_path_regex"]))
    except re.error as error:
        raise ExternalSchemaError(f"MORPHO waveform regex is invalid: {error}") from error
    baseline = [str(value) for value in mapping["baseline_blocks"]]
    fatigue = [str(value) for value in mapping["fatigue_blocks_order"]]
    blocks = baseline + fatigue
    frequencies = [str(value) for value in mapping["frequency_values"]]
    actuators = [int(value) for value in mapping["actuator_ids"]]
    repeats = [int(value) for value in mapping["repeat_ids"]]
    shape = [int(value) for value in mapping["expected_waveform_shape"]]
    if not baseline or not fatigue or len(blocks) != len(set(blocks)) or not frequencies or not actuators or not repeats or len(shape) != 2:
        raise ExternalSchemaError("MORPHO frozen topology is incomplete or duplicated")
    if mapping["sample_axis"] != 1 or mapping["time_channel_axis"] != 0 or mapping["time_channel_index"] != 0:
        raise ExternalSchemaError("MORPHO axis contract differs from the frozen HDF5 layout")
    if [int(value) for value in mapping["signal_channel_indices"]] != list(range(1, shape[0])):
        raise ExternalSchemaError("MORPHO signal-channel contract must retain all non-time rows")
    observed: dict[tuple[str, str, int, int], str] = {}
    observed_blocks: set[str] = set()
    for path, item in indexed.items():
        match = pattern.fullmatch(path)
        if match is None:
            continue
        try:
            block = str(match.group("block"))
            frequency = str(match.group("frequency"))
            actuator = int(match.group("actuator_id"))
            repeat = int(match.group("repeat_id"))
        except (IndexError, TypeError, ValueError) as error:
            raise ExternalSchemaError(f"MORPHO waveform regex lacks a frozen field: {path}") from error
        observed_blocks.add(block)
        if block not in blocks:
            continue
        _numeric_dataset(item, f"MORPHO waveform {path}")
        if item.get("shape") != shape:
            raise ExternalSchemaError(f"MORPHO waveform shape differs from frozen mapping: {path}")
        key = (block, frequency, actuator, repeat)
        if key in observed:
            raise ExternalSchemaError(f"MORPHO duplicate block/frequency/actuator/repeat cell: {key}")
        observed[key] = path
    expected = {(block, frequency, actuator, repeat) for block in blocks for frequency in frequencies for actuator in actuators for repeat in repeats}
    missing = expected - set(observed)
    extra = set(observed) - expected
    if missing or extra:
        detail = []
        if missing:
            detail.append(f"missing={sorted(missing)[:3]} (count={len(missing)})")
        if extra:
            detail.append(f"unexpected={sorted(extra)[:3]} (count={len(extra)})")
        raise ExternalSchemaError("MORPHO waveform topology differs from frozen grid: " + "; ".join(detail))
    for block in blocks:
        _require_group_attribute(indexed, f"{root}/{block}", str(mapping["block_status_attribute"]), "MORPHO block status")
        for frequency in frequencies:
            _require_group_attribute(indexed, f"{root}/{block}/{frequency}", str(mapping["sampling_rate_attribute"]), "MORPHO sampling rate")
    excluded = [str(value) for value in mapping["excluded_active_blocks"]]
    if set(excluded) & set(blocks) or set(excluded) - observed_blocks:
        raise ExternalSchemaError("MORPHO excluded-block contract differs from structural inventory")
    return {
        "status": "passed",
        "schema_mapping_id": str(mapping["mapping_id"]),
        "schema_mapping_sha256": json_hash(mapping),
        "inventory_schema_fingerprint_sha256": inventory["schema_fingerprint_sha256"],
        "active_root": root,
        "baseline_blocks": baseline,
        "fatigue_blocks_order": fatigue,
        "excluded_active_blocks": excluded,
        "monitoring_group_definition": str(mapping["monitoring_group_definition"]),
        "repeat_split_rule": str(mapping["repeat_split_rule"]),
        "component_topology": {
            "frequencies": frequencies,
            "actuator_ids": actuators,
            "repeat_ids": repeats,
            "waveform_shape": shape,
            "sample_axis": int(mapping["sample_axis"]),
            "time_channel_axis": int(mapping["time_channel_axis"]),
            "time_channel_index": int(mapping["time_channel_index"]),
            "signal_channel_count": len(mapping["signal_channel_indices"]),
            "component_packets_per_block": len(frequencies) * len(actuators) * len(repeats),
            "waveform_component_count": len(expected),
        },
        "official_state_source": str(mapping.get("official_state_source", "unresolved")),
        "hdf5_opened_for_structural_metadata": True,
        "waveform_values_read": False,
        "metadata_values_read": False,
        "attribute_values_read": False,
        "waveform_scoring_started": False,
    }


def _validate_coqtel_campaign(inventory: dict[str, Any], mapping: dict[str, Any], campaign_id: str) -> dict[str, Any]:
    _require(
        mapping,
        ("state_group_path_regex", "waveform_dataset_path_regex", "expected_waveform_shape", "sample_axis", "required_actionneur_ids", "sampling_rate_attribute_template", "ec_metadata_paths", "official_time_or_stage_path", "campaign_block_definition"),
        "COQTEL",
    )
    indexed = _index(inventory)
    state_pattern = re.compile(str(mapping["state_group_path_regex"]))
    waveform_pattern = re.compile(str(mapping["waveform_dataset_path_regex"]))
    states: dict[int, dict[str, Any]] = {}
    for path, item in indexed.items():
        match = state_pattern.fullmatch(path)
        if match is not None:
            if item.get("kind") != "group":
                raise ExternalSchemaError(f"COQTEL state path is not a group: {path}")
            state_id = int(match.group("state_id"))
            if state_id in states:
                raise ExternalSchemaError(f"COQTEL duplicate state id: {state_id}")
            states[state_id] = item
    state_ids = sorted(states)
    if not state_ids or state_ids != list(range(1, len(state_ids) + 1)):
        raise ExternalSchemaError("COQTEL state identifiers are not contiguous from one")
    shape = [int(value) for value in mapping["expected_waveform_shape"]]
    actions = {int(value) for value in mapping["required_actionneur_ids"]}
    if mapping["sample_axis"] != 1 or not actions:
        raise ExternalSchemaError("COQTEL waveform topology differs from frozen mapping")
    observed = {state: set() for state in state_ids}
    waveform_count = 0
    for path, item in indexed.items():
        match = waveform_pattern.fullmatch(path)
        if match is None:
            continue
        state_id = int(match.group("state_id"))
        actuator_id = int(match.group("actuator_id"))
        if state_id not in observed:
            raise ExternalSchemaError(f"COQTEL waveform references undeclared state {state_id}")
        _numeric_dataset(item, f"COQTEL waveform {path}")
        if item.get("shape") != shape or actuator_id in observed[state_id]:
            raise ExternalSchemaError(f"COQTEL waveform topology differs at {path}")
        observed[state_id].add(actuator_id)
        waveform_count += 1
    if any(found != actions for found in observed.values()):
        raise ExternalSchemaError("COQTEL state lacks the complete actuator set")
    for state_id in state_ids:
        attribute = str(mapping["sampling_rate_attribute_template"]).format(state_id=state_id).rsplit(":", 1)[-1]
        _require_group_attribute(indexed, f"/State_{state_id}/200kHz_5cycles", attribute, "COQTEL sampling rate")
    for path in [str(value) for value in mapping["ec_metadata_paths"]]:
        item = indexed.get(path)
        if item is None:
            raise ExternalSchemaError(f"COQTEL electrochemical metadata path is absent: {path}")
        _numeric_dataset(item, f"COQTEL electrochemical metadata {path}")
        if item.get("shape") != [len(state_ids)]:
            raise ExternalSchemaError(f"COQTEL electrochemical metadata length differs from state count: {path}")
    if str(mapping["official_time_or_stage_path"]) not in indexed or waveform_count != len(state_ids) * len(actions):
        raise ExternalSchemaError("COQTEL official time/stage or waveform grid is incomplete")
    return {
        "campaign_id": campaign_id,
        "inventory_schema_fingerprint_sha256": inventory["schema_fingerprint_sha256"],
        "state_count": len(state_ids),
        "state_id_range": [state_ids[0], state_ids[-1]],
        "actuator_ids": sorted(actions),
        "waveform_component_count": waveform_count,
        "sample_axis": int(mapping["sample_axis"]),
        "waveform_shape": shape,
        "official_time_or_stage_path": str(mapping["official_time_or_stage_path"]),
        "campaign_block_definition": str(mapping["campaign_block_definition"]),
        "waveform_values_read": False,
        "metadata_values_read": False,
        "attribute_values_read": False,
    }


def audit_coqtel_corrosion(paths: list[str | Path], mapping: dict[str, Any]) -> dict[str, Any]:
    """Validate both frozen COQTEL campaigns without reading payload values."""

    try:
        _require(mapping, ("mapping_id", "campaigns"), "COQTEL")
        campaigns = mapping["campaigns"]
        if not isinstance(campaigns, dict) or len(campaigns) != 2:
            raise ExternalSchemaError("COQTEL mapping must pin exactly two campaigns")
        seen: set[str] = set()
        summaries: list[dict[str, Any]] = []
        for value in paths:
            path = Path(value)
            if path.name not in campaigns or path.name in seen:
                raise ExternalSchemaError(f"COQTEL source is not a unique frozen campaign: {path.name}")
            seen.add(path.name)
            summaries.append(_validate_coqtel_campaign(inspect_hdf5_structure_without_values(path), mapping, str(campaigns[path.name])))
        if seen != set(campaigns):
            raise ExternalSchemaError("COQTEL schema gate did not receive both frozen campaigns")
        summaries.sort(key=lambda item: str(item["campaign_id"]))
        return {
            "status": "passed",
            "schema_mapping_id": str(mapping["mapping_id"]),
            "schema_mapping_sha256": json_hash(mapping),
            "schema_fingerprint_sha256": json_hash({"mapping": mapping, "campaigns": summaries}),
            "campaigns": summaries,
            "binary_scoring_eligibility": str(mapping.get("binary_scoring_eligibility", "unresolved")),
            "waveform_scoring_started": False,
            "waveform_values_read": False,
            "metadata_values_read": False,
            "attribute_values_read": False,
        }
    except (ExternalSchemaError, SafeMetadataError) as error:
        return {
            "status": "failed", "schema_mapping_id": str(mapping.get("mapping_id", "unresolved")),
            "schema_mapping_sha256": json_hash(mapping), "reason": str(error), "waveform_scoring_started": False,
            "waveform_values_read": False, "metadata_values_read": False, "attribute_values_read": False,
        }


def audit_morpho_fod7(path: str | Path, mapping: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe MORPHO gate result without reading HDF5 values."""

    try:
        return validate_morpho_fod7_inventory(inspect_hdf5_structure_without_values(path), mapping)
    except (ExternalSchemaError, SafeMetadataError) as error:
        return {
            "status": "failed", "schema_mapping_id": str(mapping.get("mapping_id", "unresolved")),
            "schema_mapping_sha256": json_hash(mapping), "reason": str(error), "waveform_scoring_started": False,
            "waveform_values_read": False, "metadata_values_read": False, "attribute_values_read": False,
        }
