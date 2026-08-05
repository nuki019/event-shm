"""Regression checks for the no-value MORPHO metadata-discovery boundary."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np

from src.data.mechanism_hdf5_metadata_safe_v2_4 import inspect_hdf5_structure_without_values
from src.experiments.mechanism_v2_4_metadata_discovery import load_discovery_protocol, validate_predecessor_and_input


class MorphologicalMetadataDiscoveryTests(unittest.TestCase):
    def test_inventory_reads_only_structural_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.h5"
            with h5py.File(path, "w") as handle:
                handle.attrs["campaign"] = "A"
                dataset = handle.create_dataset("blocks/waveform", data=np.ones((2, 8), dtype=np.float32), chunks=(1, 8))
                dataset.attrs["sampling_hz"] = np.float64(1_000_000)
            with patch.object(h5py.Dataset, "__getitem__", side_effect=AssertionError("dataset value access is forbidden")) as dataset_getitem, patch.object(
                h5py.AttributeManager, "__getitem__", side_effect=AssertionError("attribute value access is forbidden")
            ) as attribute_getitem:
                inventory = inspect_hdf5_structure_without_values(path)
            self.assertEqual(dataset_getitem.call_count, 0)
            self.assertEqual(attribute_getitem.call_count, 0)
            waveform = next(item for item in inventory["objects"] if item["path"] == "/blocks/waveform")
            self.assertEqual(waveform["shape"], [2, 8])
            self.assertEqual(waveform["dtype"], "float32")
            self.assertFalse(inventory["waveform_values_read"])
            self.assertFalse(inventory["metadata_values_read"])
            self.assertFalse(inventory["attribute_values_read"])

    def test_discovery_protocol_is_pinned_to_the_v23_pre_metadata_boundary(self) -> None:
        protocol, _ = load_discovery_protocol("protocols/mechanism_v2_4_morpho_metadata_discovery.json")
        invalidation_path, h5_path, receipt = validate_predecessor_and_input(protocol)
        self.assertEqual(invalidation_path.name, "mechanism_v2_3_invalidation_receipt.json")
        self.assertEqual(h5_path.name, "MORPHO_FOD7.h5")
        self.assertEqual(receipt["dataset_id"], "morpho_fod7")
        self.assertTrue(protocol["input_integrity_history"]["historical_only"])


if __name__ == "__main__":
    unittest.main()
