"""HDF5 structural inventory that never dereferences dataset or attribute values.

This v2.5-owned module is frozen with the successor.  It intentionally uses
only object names, shapes, dtypes, and attribute names/type descriptors until
the separately frozen one-shot runner is allowed to read waveform values.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import h5py


class SafeMetadataError(ValueError):
    """Raised when a structural-only HDF5 inventory cannot be produced."""


def _normal_path(name: str) -> str:
    return "/" if name in {"", "/"} else "/" + name.strip("/")


def _attribute_descriptors(attributes: h5py.AttributeManager) -> dict[str, dict[str, Any]]:
    descriptors: dict[str, dict[str, Any]] = {}
    for key in sorted(attributes.keys()):
        attribute_id = attributes.get_id(key)
        descriptors[str(key)] = {"shape": list(attribute_id.shape), "dtype": str(attribute_id.dtype)}
    return descriptors


def inventory_fingerprint(inventory: dict[str, Any]) -> str:
    canonical = {key: value for key, value in inventory.items() if key != "schema_fingerprint_sha256"}
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def inspect_hdf5_structure_without_values(path: str | Path) -> dict[str, Any]:
    """Return deterministic HDF5 structure without materializing values."""

    source = Path(path)
    if not source.is_file():
        raise SafeMetadataError(f"HDF5 source does not exist: {source}")
    objects: list[dict[str, Any]] = []
    try:
        with h5py.File(source, "r") as handle:
            objects.append({"path": "/", "kind": "group", "attributes": _attribute_descriptors(handle.attrs)})

            def visitor(name: str, value: h5py.Group | h5py.Dataset) -> None:
                item: dict[str, Any] = {
                    "path": _normal_path(name),
                    "kind": "dataset" if isinstance(value, h5py.Dataset) else "group",
                    "attributes": _attribute_descriptors(value.attrs),
                }
                if isinstance(value, h5py.Dataset):
                    item.update(
                        {
                            "shape": list(value.shape),
                            "dtype": str(value.dtype),
                            "ndim": int(value.ndim),
                            "chunks": None if value.chunks is None else list(value.chunks),
                            "compression": value.compression,
                        }
                    )
                objects.append(item)

            handle.visititems(visitor)
    except OSError as error:
        raise SafeMetadataError(f"cannot inspect HDF5 structural metadata: {error}") from error
    objects.sort(key=lambda item: (str(item["path"]), str(item["kind"])))
    inventory = {
        "schema": "mechanism-v2.5-hdf5-structural-metadata-v1",
        "file_name": source.name,
        "objects": objects,
        "waveform_values_read": False,
        "metadata_values_read": False,
        "attribute_values_read": False,
    }
    inventory["schema_fingerprint_sha256"] = inventory_fingerprint(inventory)
    return inventory
