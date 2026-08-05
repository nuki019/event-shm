"""Regression tests for the versioned v2.2 hierarchical schema successor."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from src.data.mechanism_hdf5_schema_v2_2 import audit_coqtel_hierarchy
from src.experiments.mechanism_v2_2_successor import SuccessorError, load_successor_manifest, load_successor_protocol, verify_successor_freeze


def _mapping() -> dict:
    return {
        "mapping_id": "test-coqtel-hierarchy-v1",
        "campaigns": {
            "Essai_Corrosion1.h5": "campaign_1",
            "Essai_Corrosion2.h5": "campaign_2",
        },
        "state_group_path_regex": r"^/State_(?P<state_id>[1-9][0-9]*)$",
        "waveform_dataset_path_regex": r"^/State_(?P<state_id>[1-9][0-9]*)/200kHz_5cycles/Actionneur(?P<actuator_id>[1-4])/measured_data_rep_1\.mat$",
        "waveform_shape": [5, 2000],
        "sample_axis": 1,
        "required_actionneur_ids": [1, 2, 3, 4],
        "sampling_rate_attribute_template": "attr:/State_{state_id}/200kHz_5cycles:fs",
        "ec_metadata_paths": ["/EC_data/EC_time", "/EC_data/EC_potential", "/EC_data/EC_current"],
        "measurement_uid_template": "{campaign_id}:state:{state_id}:actuator:{actuator_id}:rep:1",
        "campaign_block_template": "{campaign_id}:state:{state_id}",
    }


def _write_campaign(path: Path, include_fourth_actuator: bool = True) -> None:
    with h5py.File(path, "w") as handle:
        ec = handle.create_group("EC_data")
        for name in ("EC_time", "EC_potential", "EC_current"):
            ec.create_dataset(name, data=np.arange(2, dtype=np.float64))
        for state_id in (1, 2):
            frequency = handle.create_group(f"State_{state_id}/200kHz_5cycles")
            frequency.attrs["fs"] = 1_000_000.0
            for actuator_id in range(1, 5 if include_fourth_actuator else 4):
                actionneur = frequency.create_group(f"Actionneur{actuator_id}")
                actionneur.create_dataset("measured_data_rep_1.mat", data=np.zeros((5, 2000), dtype=np.float64))


class MechanismV22Tests(unittest.TestCase):
    def test_hierarchical_coqtel_gate_uses_structure_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "Essai_Corrosion1.h5"
            second = root / "Essai_Corrosion2.h5"
            _write_campaign(first)
            _write_campaign(second)
            output = audit_coqtel_hierarchy([first, second], _mapping())
            self.assertEqual(output["status"], "passed")
            self.assertFalse(output["waveform_values_read"])
            self.assertFalse(output["metadata_values_read"])
            self.assertEqual([item["monitoring_block_count"] for item in output["campaigns"]], [2, 2])

    def test_hierarchical_coqtel_gate_rejects_incomplete_path_grid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "Essai_Corrosion1.h5"
            second = root / "Essai_Corrosion2.h5"
            _write_campaign(first)
            _write_campaign(second, include_fourth_actuator=False)
            output = audit_coqtel_hierarchy([first, second], _mapping())
            self.assertEqual(output["status"], "failed")
            self.assertIn("actuator", output["reason"])

    def test_v22_overlay_resolves_but_its_invalidated_freeze_is_not_reused(self) -> None:
        protocol, overlay = load_successor_protocol("protocols/mechanism_v2_2.json")
        manifest, manifest_overlay = load_successor_manifest("protocols/mechanism_v2_2_data_manifest.json")
        self.assertEqual(protocol["protocol_id"], "mechanism-v2.2")
        self.assertEqual(overlay["inherits"]["protocol_path"], "protocols/mechanism_v2_1.json")
        self.assertEqual(manifest_overlay["inherits"]["manifest_path"], "protocols/mechanism_v2_1_data_manifest.json")
        self.assertTrue(any(entry["dataset_id"] == "coqtel_corrosion" for entry in manifest["data_sets"]))
        with self.assertRaises(SuccessorError):
            verify_successor_freeze(
                "protocols/mechanism_v2_2.json",
                "protocols/mechanism_v2_2_data_manifest.json",
                "protocols/mechanism_v2_2_freeze_receipt.json",
            )


if __name__ == "__main__":
    unittest.main()
