"""Metadata-only HDF5 schema gate for mechanism-v2 external data.

The inventory deliberately visits object names, shapes, dtypes, and
attribute names without dereferencing waveform arrays.  A human-readable
mapping can then be frozen before any waveform scoring begins.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np


class Hdf5SchemaError(ValueError):
    """Raised when a proposed external HDF5 mapping is not auditable."""


def _normal_path(name: str) -> str:
    return "/" if name in {"", "/"} else "/" + name.strip("/")


def _attribute_metadata(attributes: h5py.AttributeManager) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for key in sorted(attributes.keys()):
        value = attributes[key]
        array = np.asarray(value)
        inventory[str(key)] = {
            "shape": list(array.shape),
            "dtype": str(array.dtype),
        }
    return inventory


def inspect_hdf5_metadata(path: str | Path) -> dict[str, Any]:
    """Return a canonical structure inventory without reading dataset values."""

    path = Path(path)
    if not path.is_file():
        raise Hdf5SchemaError(f"HDF5 file does not exist: {path}")
    objects: list[dict[str, Any]] = []
    with h5py.File(path, "r") as handle:
        objects.append(
            {
                "path": "/",
                "kind": "group",
                "attributes": _attribute_metadata(handle.attrs),
            }
        )

        def visitor(name: str, value: h5py.Group | h5py.Dataset) -> None:
            item: dict[str, Any] = {
                "path": _normal_path(name),
                "kind": "dataset" if isinstance(value, h5py.Dataset) else "group",
                "attributes": _attribute_metadata(value.attrs),
            }
            if isinstance(value, h5py.Dataset):
                item.update(
                    {
                        "shape": list(value.shape),
                        "dtype": str(value.dtype),
                        "size": int(value.size),
                        "ndim": int(value.ndim),
                    }
                )
            objects.append(item)

        handle.visititems(visitor)
    objects.sort(key=lambda item: (item["path"], item["kind"]))
    inventory = {
        "schema": "mechanism-v2-hdf5-metadata-v1",
        "file_name": path.name,
        "objects": objects,
    }
    inventory["schema_fingerprint_sha256"] = schema_fingerprint(inventory)
    return inventory


def schema_fingerprint(inventory: dict[str, Any]) -> str:
    """Hash only the stable schema fields, excluding the generated hash itself."""

    canonical = {key: value for key, value in inventory.items() if key != "schema_fingerprint_sha256"}
    encoded = json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _object_index(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects = inventory.get("objects")
    if not isinstance(objects, list):
        raise Hdf5SchemaError("HDF5 inventory lacks objects")
    indexed = {str(item.get("path")): item for item in objects if isinstance(item, dict) and isinstance(item.get("path"), str)}
    if not indexed:
        raise Hdf5SchemaError("HDF5 inventory has no addressable objects")
    return indexed


def _reference_exists(reference: str, indexed: dict[str, dict[str, Any]]) -> bool:
    if reference.startswith("attr:"):
        try:
            _, object_path, attribute = reference.split(":", 2)
        except ValueError:
            return False
        return object_path in indexed and attribute in indexed[object_path].get("attributes", {})
    return reference in indexed and indexed[reference].get("kind") == "dataset"


def validate_schema_mapping(inventory: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    """Validate a pre-score semantic mapping against metadata-only inventory.

    ``mapping`` uses dataset paths (for example ``/measurement/time``) or
    attribute references in the form ``attr:/measurement:sampling_rate_hz``.
    Values are not dereferenced here; this gate only proves that declared
    fields are structurally present before waveform arrays are touched.
    """

    indexed = _object_index(inventory)
    required = (
        "waveform_dataset_path",
        "sample_axis",
        "measurement_uid_field",
        "group_field",
        "state_label_field",
        "sampling_rate_field",
    )
    missing = [field for field in required if field not in mapping]
    if missing:
        raise Hdf5SchemaError(f"schema mapping lacks required fields: {missing}")
    waveform_path = str(mapping["waveform_dataset_path"])
    waveform = indexed.get(waveform_path)
    if waveform is None or waveform.get("kind") != "dataset":
        raise Hdf5SchemaError("waveform_dataset_path does not identify a dataset")
    dtype = np.dtype(str(waveform.get("dtype")))
    if dtype.kind not in {"i", "u", "f"} or int(waveform.get("ndim", 0)) < 2:
        raise Hdf5SchemaError("waveform dataset must be a numeric array with at least two dimensions")
    sample_axis = mapping["sample_axis"]
    if not isinstance(sample_axis, int) or not 0 <= sample_axis < int(waveform["ndim"]):
        raise Hdf5SchemaError("sample_axis is outside waveform dimensions")
    semantic_fields = ("measurement_uid_field", "group_field", "state_label_field", "sampling_rate_field")
    unresolved = [field for field in semantic_fields if not _reference_exists(str(mapping[field]), indexed)]
    if unresolved:
        raise Hdf5SchemaError(f"schema mapping references absent fields: {unresolved}")
    repeat_field = mapping.get("repeat_field")
    if repeat_field is not None and not _reference_exists(str(repeat_field), indexed):
        raise Hdf5SchemaError("repeat_field is absent from metadata inventory")
    transmitter_field = mapping.get("transmitter_field")
    receiver_field = mapping.get("receiver_field")
    if (transmitter_field is None) != (receiver_field is None):
        raise Hdf5SchemaError("transmitter_field and receiver_field must be declared together")
    for name, reference in (("transmitter_field", transmitter_field), ("receiver_field", receiver_field)):
        if reference is not None and not _reference_exists(str(reference), indexed):
            raise Hdf5SchemaError(f"{name} is absent from metadata inventory")
    return {
        "status": "passed",
        "schema_fingerprint_sha256": schema_fingerprint(inventory),
        "waveform_dataset_path": waveform_path,
        "sample_axis": sample_axis,
        "measurement_uid_field": str(mapping["measurement_uid_field"]),
        "group_field": str(mapping["group_field"]),
        "state_label_field": str(mapping["state_label_field"]),
        "sampling_rate_field": str(mapping["sampling_rate_field"]),
        "repeat_field": None if repeat_field is None else str(repeat_field),
        "transmitter_field": None if transmitter_field is None else str(transmitter_field),
        "receiver_field": None if receiver_field is None else str(receiver_field),
    }


def schema_gate_result(inventory: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe pass/fail result for a manifest exclusion receipt."""

    try:
        return validate_schema_mapping(inventory, mapping)
    except Hdf5SchemaError as error:
        return {
            "status": "failed",
            "schema_fingerprint_sha256": schema_fingerprint(inventory),
            "reason": str(error),
        }
