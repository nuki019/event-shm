"""Hierarchical, metadata-only external-schema gate for mechanism-v2.2.

COQTEL exposes monitoring records through HDF5 object paths rather than a flat
waveform table.  This module validates only names, HDF5 shapes, dtypes, and
attribute names returned by :mod:`mechanism_hdf5_schema`; it never indexes a
waveform dataset or an EC metadata value.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from src.data.mechanism_hdf5_schema import Hdf5SchemaError, inspect_hdf5_metadata
from src.experiments.mechanism_v2_2_successor import json_hash


class HierarchicalSchemaError(Hdf5SchemaError):
    """Raised when a path-template mapping is not satisfied by HDF5 metadata."""


def _index(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects = inventory.get("objects")
    if not isinstance(objects, list):
        raise HierarchicalSchemaError("metadata inventory has no object list")
    indexed = {item.get("path"): item for item in objects if isinstance(item, dict) and isinstance(item.get("path"), str)}
    if not indexed:
        raise HierarchicalSchemaError("metadata inventory has no indexed HDF5 objects")
    return indexed


def _numeric_dataset(item: dict[str, Any], label: str) -> None:
    if item.get("kind") != "dataset":
        raise HierarchicalSchemaError(f"{label} is not a dataset")
    try:
        dtype = np.dtype(str(item.get("dtype")))
    except TypeError as error:
        raise HierarchicalSchemaError(f"{label} has no valid dtype") from error
    if dtype.kind not in {"i", "u", "f"}:
        raise HierarchicalSchemaError(f"{label} is not numeric")


def _sampling_attribute(item: dict[str, Any], state_id: int, mapping: dict[str, Any]) -> None:
    template = mapping.get("sampling_rate_attribute_template")
    if not isinstance(template, str) or not template.startswith("attr:"):
        raise HierarchicalSchemaError("mapping has no attr: sampling-rate template")
    reference = template[5:].format(state_id=state_id)
    try:
        object_path, attribute = reference.rsplit(":", 1)
    except ValueError as error:
        raise HierarchicalSchemaError("sampling-rate attribute template is malformed") from error
    if item.get("path") != object_path or attribute not in item.get("attributes", {}):
        raise HierarchicalSchemaError(f"state {state_id} lacks the declared sampling-rate attribute")


def validate_coqtel_inventory(inventory: dict[str, Any], mapping: dict[str, Any], campaign_id: str) -> dict[str, Any]:
    """Validate one COQTEL campaign solely from its metadata inventory."""

    required = (
        "mapping_id",
        "state_group_path_regex",
        "waveform_dataset_path_regex",
        "waveform_shape",
        "sample_axis",
        "required_actionneur_ids",
        "sampling_rate_attribute_template",
        "ec_metadata_paths",
        "measurement_uid_template",
        "campaign_block_template",
    )
    missing = [key for key in required if key not in mapping]
    if missing:
        raise HierarchicalSchemaError(f"mapping lacks required fields: {missing}")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise HierarchicalSchemaError("campaign identifier is missing")
    indexed = _index(inventory)
    try:
        state_pattern = re.compile(str(mapping["state_group_path_regex"]))
        waveform_pattern = re.compile(str(mapping["waveform_dataset_path_regex"]))
    except re.error as error:
        raise HierarchicalSchemaError(f"mapping regex is invalid: {error}") from error
    expected_shape = [int(value) for value in mapping["waveform_shape"]]
    sample_axis = mapping["sample_axis"]
    if not isinstance(sample_axis, int) or not 0 <= sample_axis < len(expected_shape):
        raise HierarchicalSchemaError("sample_axis is outside the declared waveform shape")
    expected_actions = {int(value) for value in mapping["required_actionneur_ids"]}
    if not expected_actions:
        raise HierarchicalSchemaError("mapping has no required actuator ids")

    states: dict[int, dict[str, Any]] = {}
    for path, item in indexed.items():
        match = state_pattern.fullmatch(path)
        if match is not None:
            if item.get("kind") != "group":
                raise HierarchicalSchemaError(f"state path is not a group: {path}")
            state_id = int(match.group("state_id"))
            if state_id in states:
                raise HierarchicalSchemaError(f"duplicate state id: {state_id}")
            states[state_id] = item
    if not states:
        raise HierarchicalSchemaError("no state groups match the frozen path pattern")
    state_ids = sorted(states)
    if state_ids != list(range(1, len(state_ids) + 1)):
        raise HierarchicalSchemaError("state group identifiers are not contiguous from 1")

    actions_by_state: dict[int, set[int]] = {state_id: set() for state_id in state_ids}
    waveform_count = 0
    for path, item in indexed.items():
        match = waveform_pattern.fullmatch(path)
        if match is None:
            continue
        state_id = int(match.group("state_id"))
        actuator_id = int(match.group("actuator_id"))
        if state_id not in actions_by_state:
            raise HierarchicalSchemaError(f"waveform path references undeclared state {state_id}")
        _numeric_dataset(item, f"waveform {path}")
        if item.get("shape") != expected_shape:
            raise HierarchicalSchemaError(f"waveform shape differs from frozen mapping: {path}")
        if actuator_id in actions_by_state[state_id]:
            raise HierarchicalSchemaError(f"duplicate actuator waveform for state {state_id}")
        actions_by_state[state_id].add(actuator_id)
        waveform_count += 1
    for state_id, actions in actions_by_state.items():
        if actions != expected_actions:
            raise HierarchicalSchemaError(f"state {state_id} lacks the complete declared actuator set")
        frequency_path = f"/State_{state_id}/200kHz_5cycles"
        frequency_item = indexed.get(frequency_path)
        if frequency_item is None or frequency_item.get("kind") != "group":
            raise HierarchicalSchemaError(f"state {state_id} lacks its declared frequency group")
        _sampling_attribute(frequency_item, state_id, mapping)

    ec_paths = mapping["ec_metadata_paths"]
    if not isinstance(ec_paths, list) or not ec_paths:
        raise HierarchicalSchemaError("mapping has no EC metadata paths")
    for path in ec_paths:
        item = indexed.get(str(path))
        if item is None:
            raise HierarchicalSchemaError(f"EC metadata path is absent: {path}")
        _numeric_dataset(item, f"EC metadata {path}")
        shape = item.get("shape")
        if not isinstance(shape, list) or len(shape) != 1 or int(shape[0]) != len(state_ids):
            raise HierarchicalSchemaError(f"EC metadata length does not match the state groups: {path}")

    record_count = len(state_ids) * len(expected_actions)
    if waveform_count != record_count:
        raise HierarchicalSchemaError("waveform path count differs from the declared state/actuator grid")
    return {
        "campaign_id": campaign_id,
        "inventory_schema_fingerprint_sha256": inventory["schema_fingerprint_sha256"],
        "state_count": len(state_ids),
        "state_id_range": [state_ids[0], state_ids[-1]],
        "actuator_ids": sorted(expected_actions),
        "monitoring_block_count": len(state_ids),
        "waveform_component_count": waveform_count,
        "sample_axis": sample_axis,
        "waveform_shape": expected_shape,
        "ec_metadata_paths": [str(path) for path in ec_paths],
        "waveform_values_read": False,
        "metadata_values_read": False,
    }


def audit_coqtel_hierarchy(paths: list[str | Path], mapping: dict[str, Any]) -> dict[str, Any]:
    """Return a reproducible pass/fail gate for both COQTEL campaigns."""

    try:
        campaigns = mapping.get("campaigns")
        if not isinstance(campaigns, dict) or len(campaigns) != 2:
            raise HierarchicalSchemaError("mapping must pin exactly two COQTEL campaigns")
        summaries: list[dict[str, Any]] = []
        observed_names: set[str] = set()
        for path_value in paths:
            path = Path(path_value)
            if path.name not in campaigns:
                raise HierarchicalSchemaError(f"file is not an explicitly mapped campaign: {path.name}")
            observed_names.add(path.name)
            inventory = inspect_hdf5_metadata(path)
            summaries.append(validate_coqtel_inventory(inventory, mapping, str(campaigns[path.name])))
        if observed_names != set(campaigns):
            raise HierarchicalSchemaError("schema audit did not receive exactly the two frozen campaign files")
        summaries.sort(key=lambda item: str(item["campaign_id"]))
        canonical = {
            "mapping": mapping,
            "campaigns": summaries,
        }
        return {
            "status": "passed",
            "schema_mapping_id": str(mapping["mapping_id"]),
            "schema_mapping_sha256": json_hash(mapping),
            "schema_fingerprint_sha256": json_hash(canonical),
            "campaigns": summaries,
            "waveform_scoring_started": False,
            "waveform_values_read": False,
            "metadata_values_read": False,
        }
    except HierarchicalSchemaError as error:
        return {
            "status": "failed",
            "schema_mapping_id": str(mapping.get("mapping_id", "unresolved")),
            "schema_mapping_sha256": json_hash(mapping),
            "reason": str(error),
            "waveform_scoring_started": False,
            "waveform_values_read": False,
            "metadata_values_read": False,
        }
