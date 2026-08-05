"""Dataset-specific, metadata-only schema gates for mechanism-v2.4.

The gates operate on the structural inventory supplied by
``mechanism_hdf5_metadata_safe_v2_4``.  They are intentionally limited to
object names, shapes, dtypes, and attribute names/types.  In particular, no
dataset or attribute value is dereferenced while determining eligibility.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np

from src.data.mechanism_hdf5_metadata_safe_v2_4 import SafeMetadataError, inspect_hdf5_structure_without_values
from src.experiments.mechanism_v2_4_successor import json_hash


class ExternalSchemaError(ValueError):
    """Raised when a frozen v2.4 external schema mapping is not satisfied."""


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


def _group_with_attribute(indexed: dict[str, dict[str, Any]], path: str, attribute: str, label: str) -> None:
    item = indexed.get(path)
    if item is None or item.get("kind") != "group":
        raise ExternalSchemaError(f"{label} group is absent: {path}")
    if attribute not in item.get("attributes", {}):
        raise ExternalSchemaError(f"{label} lacks required attribute name {attribute!r}: {path}")


def _require_mapping(mapping: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise ExternalSchemaError(f"{label} mapping lacks required fields: {missing}")


def validate_morpho_fod7_inventory(inventory: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    """Validate the frozen MORPHO Active/fatigue mapping without values."""

    _require_mapping(
        mapping,
        (
            "mapping_id",
            "active_root",
            "waveform_dataset_path_regex",
            "expected_waveform_shape",
            "sample_axis",
            "time_channel_axis",
            "time_channel_index",
            "signal_channel_indices",
            "frequency_values",
            "actuator_ids",
            "repeat_ids",
            "baseline_blocks",
            "fatigue_blocks_order",
            "excluded_active_blocks",
            "block_status_attribute",
            "sampling_rate_attribute",
            "monitoring_group_definition",
            "repeat_split_rule",
        ),
        "MORPHO",
    )
    indexed = _index(inventory)
    root = str(mapping["active_root"])
    if indexed.get(root, {}).get("kind") != "group":
        raise ExternalSchemaError("MORPHO active root is absent")
    try:
        waveform_pattern = re.compile(str(mapping["waveform_dataset_path_regex"]))
    except re.error as error:
        raise ExternalSchemaError(f"MORPHO waveform regex is invalid: {error}") from error

    baseline_blocks = [str(value) for value in mapping["baseline_blocks"]]
    fatigue_blocks = [str(value) for value in mapping["fatigue_blocks_order"]]
    all_blocks = baseline_blocks + fatigue_blocks
    if not baseline_blocks or not fatigue_blocks or len(all_blocks) != len(set(all_blocks)):
        raise ExternalSchemaError("MORPHO baseline/fatigue block definitions are empty or overlap")
    frequencies = [str(value) for value in mapping["frequency_values"]]
    actuators = [int(value) for value in mapping["actuator_ids"]]
    repeats = [int(value) for value in mapping["repeat_ids"]]
    expected_shape = [int(value) for value in mapping["expected_waveform_shape"]]
    if not frequencies or not actuators or not repeats or len(expected_shape) != 2:
        raise ExternalSchemaError("MORPHO topology definition is incomplete")
    if mapping["sample_axis"] != 1 or mapping["time_channel_axis"] != 0 or mapping["time_channel_index"] != 0:
        raise ExternalSchemaError("MORPHO axis contract differs from the frozen h5py layout")
    if [int(value) for value in mapping["signal_channel_indices"]] != list(range(1, expected_shape[0])):
        raise ExternalSchemaError("MORPHO signal-channel contract must retain every non-time channel")

    status_name = str(mapping["block_status_attribute"])
    sampling_name = str(mapping["sampling_rate_attribute"])
    observed: dict[tuple[str, str, int, int], str] = {}
    observed_blocks: set[str] = set()
    for path, item in indexed.items():
        match = waveform_pattern.fullmatch(path)
        if match is None:
            continue
        groups = match.groupdict()
        try:
            block = str(groups["block"])
            frequency = str(groups["frequency"])
            actuator = int(groups["actuator_id"])
            repeat = int(groups["repeat_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalSchemaError(f"MORPHO waveform regex does not expose frozen path fields: {path}") from error
        observed_blocks.add(block)
        if block not in all_blocks:
            continue
        _numeric_dataset(item, f"MORPHO waveform {path}")
        if item.get("shape") != expected_shape:
            raise ExternalSchemaError(f"MORPHO waveform shape differs from frozen mapping: {path}")
        key = (block, frequency, actuator, repeat)
        if key in observed:
            raise ExternalSchemaError(f"MORPHO duplicate block/frequency/actuator/repeat cell: {key}")
        observed[key] = path

    expected_cells = {(block, frequency, actuator, repeat) for block in all_blocks for frequency in frequencies for actuator in actuators for repeat in repeats}
    absent = sorted(expected_cells - set(observed))
    extra = sorted(set(observed) - expected_cells)
    if absent or extra:
        message = []
        if absent:
            message.append(f"missing={absent[:3]} (count={len(absent)})")
        if extra:
            message.append(f"unexpected={extra[:3]} (count={len(extra)})")
        raise ExternalSchemaError("MORPHO waveform topology differs from frozen grid: " + "; ".join(message))

    for block in all_blocks:
        _group_with_attribute(indexed, f"{root}/{block}", status_name, "MORPHO block status")
        for frequency in frequencies:
            _group_with_attribute(indexed, f"{root}/{block}/{frequency}", sampling_name, "MORPHO sampling rate")
    excluded = [str(value) for value in mapping["excluded_active_blocks"]]
    if set(excluded) & set(all_blocks):
        raise ExternalSchemaError("MORPHO excluded blocks overlap the scored mapping")
    if set(excluded) - observed_blocks:
        raise ExternalSchemaError("MORPHO declared excluded active blocks are absent from the structural inventory")

    return {
        "status": "passed",
        "schema_mapping_id": str(mapping["mapping_id"]),
        "schema_mapping_sha256": json_hash(mapping),
        "inventory_schema_fingerprint_sha256": inventory["schema_fingerprint_sha256"],
        "active_root": root,
        "baseline_blocks": baseline_blocks,
        "fatigue_blocks_order": fatigue_blocks,
        "excluded_active_blocks": excluded,
        "monitoring_group_definition": str(mapping["monitoring_group_definition"]),
        "repeat_split_rule": str(mapping["repeat_split_rule"]),
        "component_topology": {
            "frequencies": frequencies,
            "actuator_ids": actuators,
            "repeat_ids": repeats,
            "waveform_shape": expected_shape,
            "sample_axis": int(mapping["sample_axis"]),
            "time_channel_axis": int(mapping["time_channel_axis"]),
            "time_channel_index": int(mapping["time_channel_index"]),
            "signal_channel_count": len(mapping["signal_channel_indices"]),
            "waveform_component_count": len(expected_cells),
        },
        "official_state_source": str(mapping.get("official_state_source", "unresolved")),
        "hdf5_opened_for_structural_metadata": True,
        "waveform_values_read": False,
        "metadata_values_read": False,
        "attribute_values_read": False,
        "waveform_scoring_started": False,
    }


def _validate_coqtel_campaign(inventory: dict[str, Any], mapping: dict[str, Any], campaign_id: str) -> dict[str, Any]:
    _require_mapping(
        mapping,
        (
            "state_group_path_regex",
            "waveform_dataset_path_regex",
            "expected_waveform_shape",
            "sample_axis",
            "required_actionneur_ids",
            "sampling_rate_attribute_template",
            "ec_metadata_paths",
            "official_time_or_stage_path",
            "campaign_block_definition",
        ),
        "COQTEL",
    )
    indexed = _index(inventory)
    try:
        state_pattern = re.compile(str(mapping["state_group_path_regex"]))
        waveform_pattern = re.compile(str(mapping["waveform_dataset_path_regex"]))
    except re.error as error:
        raise ExternalSchemaError(f"COQTEL path regex is invalid: {error}") from error
    states: dict[int, dict[str, Any]] = {}
    for path, item in indexed.items():
        match = state_pattern.fullmatch(path)
        if match is None:
            continue
        if item.get("kind") != "group":
            raise ExternalSchemaError(f"COQTEL state path is not a group: {path}")
        state_id = int(match.group("state_id"))
        if state_id in states:
            raise ExternalSchemaError(f"COQTEL duplicate state id: {state_id}")
        states[state_id] = item
    if not states:
        raise ExternalSchemaError("COQTEL has no state groups matching the frozen mapping")
    state_ids = sorted(states)
    if state_ids != list(range(1, len(state_ids) + 1)):
        raise ExternalSchemaError("COQTEL state identifiers are not contiguous from one")

    expected_shape = [int(value) for value in mapping["expected_waveform_shape"]]
    expected_actions = {int(value) for value in mapping["required_actionneur_ids"]}
    if not expected_actions or mapping["sample_axis"] != 1:
        raise ExternalSchemaError("COQTEL waveform topology differs from the frozen mapping")
    actions_by_state = {state_id: set() for state_id in state_ids}
    waveform_count = 0
    for path, item in indexed.items():
        match = waveform_pattern.fullmatch(path)
        if match is None:
            continue
        state_id = int(match.group("state_id"))
        actuator_id = int(match.group("actuator_id"))
        if state_id not in actions_by_state:
            raise ExternalSchemaError(f"COQTEL waveform references undeclared state {state_id}")
        _numeric_dataset(item, f"COQTEL waveform {path}")
        if item.get("shape") != expected_shape:
            raise ExternalSchemaError(f"COQTEL waveform shape differs from frozen mapping: {path}")
        if actuator_id in actions_by_state[state_id]:
            raise ExternalSchemaError(f"COQTEL duplicate actuator waveform in state {state_id}")
        actions_by_state[state_id].add(actuator_id)
        waveform_count += 1
    for state_id, actions in actions_by_state.items():
        if actions != expected_actions:
            raise ExternalSchemaError(f"COQTEL state {state_id} lacks the complete actuator set")
        frequency_path = f"/State_{state_id}/200kHz_5cycles"
        _group_with_attribute(
            indexed,
            frequency_path,
            str(mapping["sampling_rate_attribute_template"]).format(state_id=state_id).rsplit(":", 1)[-1],
            "COQTEL sampling rate",
        )
    for path in [str(value) for value in mapping["ec_metadata_paths"]]:
        item = indexed.get(path)
        if item is None:
            raise ExternalSchemaError(f"COQTEL electrochemical metadata path is absent: {path}")
        _numeric_dataset(item, f"COQTEL electrochemical metadata {path}")
        if item.get("shape") != [len(state_ids)]:
            raise ExternalSchemaError(f"COQTEL electrochemical metadata length differs from state count: {path}")
    time_path = str(mapping["official_time_or_stage_path"])
    if time_path not in indexed:
        raise ExternalSchemaError("COQTEL has no frozen official time/corrosion-stage field")
    if waveform_count != len(state_ids) * len(expected_actions):
        raise ExternalSchemaError("COQTEL waveform count differs from the frozen state/actuator grid")
    return {
        "campaign_id": campaign_id,
        "inventory_schema_fingerprint_sha256": inventory["schema_fingerprint_sha256"],
        "state_count": len(state_ids),
        "state_id_range": [state_ids[0], state_ids[-1]],
        "actuator_ids": sorted(expected_actions),
        "waveform_component_count": waveform_count,
        "sample_axis": int(mapping["sample_axis"]),
        "waveform_shape": expected_shape,
        "official_time_or_stage_path": time_path,
        "campaign_block_definition": str(mapping["campaign_block_definition"]),
        "waveform_values_read": False,
        "metadata_values_read": False,
        "attribute_values_read": False,
    }


def audit_coqtel_corrosion(paths: list[str | Path], mapping: dict[str, Any]) -> dict[str, Any]:
    """Validate both frozen COQTEL campaigns without reading payload values."""

    try:
        _require_mapping(mapping, ("mapping_id", "campaigns"), "COQTEL")
        campaigns = mapping["campaigns"]
        if not isinstance(campaigns, dict) or len(campaigns) != 2:
            raise ExternalSchemaError("COQTEL mapping must pin exactly two campaigns")
        observed_names: set[str] = set()
        summaries: list[dict[str, Any]] = []
        for value in paths:
            path = Path(value)
            if path.name not in campaigns:
                raise ExternalSchemaError(f"COQTEL source is not a frozen campaign: {path.name}")
            if path.name in observed_names:
                raise ExternalSchemaError(f"COQTEL campaign is duplicated: {path.name}")
            observed_names.add(path.name)
            inventory = inspect_hdf5_structure_without_values(path)
            summaries.append(_validate_coqtel_campaign(inventory, mapping, str(campaigns[path.name])))
        if observed_names != set(campaigns):
            raise ExternalSchemaError("COQTEL schema gate did not receive exactly both frozen campaigns")
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
            "status": "failed",
            "schema_mapping_id": str(mapping.get("mapping_id", "unresolved")),
            "schema_mapping_sha256": json_hash(mapping),
            "reason": str(error),
            "waveform_scoring_started": False,
            "waveform_values_read": False,
            "metadata_values_read": False,
            "attribute_values_read": False,
        }


def audit_morpho_fod7(path: str | Path, mapping: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe MORPHO gate result without reading HDF5 values."""

    try:
        inventory = inspect_hdf5_structure_without_values(path)
        return validate_morpho_fod7_inventory(inventory, mapping)
    except (ExternalSchemaError, SafeMetadataError) as error:
        return {
            "status": "failed",
            "schema_mapping_id": str(mapping.get("mapping_id", "unresolved")),
            "schema_mapping_sha256": json_hash(mapping),
            "reason": str(error),
            "waveform_scoring_started": False,
            "waveform_values_read": False,
            "metadata_values_read": False,
            "attribute_values_read": False,
        }
