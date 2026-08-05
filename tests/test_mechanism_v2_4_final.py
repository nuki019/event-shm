"""Regression checks for the final mechanism-v2.4 pre-access boundary."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np

from src.data.mechanism_v2_4_external_schema import audit_coqtel_corrosion, audit_morpho_fod7
from src.experiments import e9_mechanism_v2_4_ogw
from src.experiments.mechanism_v2_4_successor import external_mapping, load_v24_manifest, load_v24_protocol


def _morpho_mapping() -> dict:
    protocol, _ = load_v24_protocol("protocols/mechanism_v2_4.json")
    mapping = external_mapping(protocol, "morpho_fod7")
    mapping.update(
        {
            "baseline_blocks": ["Healthy_A", "Healthy_B"],
            "fatigue_blocks_order": ["4kN_200"],
            "excluded_active_blocks": ["AfterImpact_A"],
            "frequency_values": ["100kHz"],
            "actuator_ids": [1],
            "repeat_ids": [1, 2],
        }
    )
    return mapping


def _write_morpho_fixture(path: Path, mapping: dict, *, omit_repeat: bool = False) -> None:
    with h5py.File(path, "w") as handle:
        root = handle.create_group("5_Active")
        for block in mapping["baseline_blocks"] + mapping["fatigue_blocks_order"] + mapping["excluded_active_blocks"]:
            block_group = root.create_group(block)
            block_group.attrs["Status"] = "structural-test-only"
            frequency = block_group.create_group("100kHz")
            frequency.attrs["fs"] = 1_000_000.0
            actuator = frequency.create_group("Actionneur1")
            repeats = [1, 2]
            if omit_repeat and block == "4kN_200":
                repeats = [1]
            for repeat in repeats:
                actuator.create_dataset(f"measured_data_rep_{repeat}.mat", data=np.ones((30, 5001), dtype=np.float64))


def _write_coqtel_fixture(path: Path, state_count: int) -> None:
    with h5py.File(path, "w") as handle:
        ec = handle.create_group("EC_data")
        for name in ("EC_time", "EC_potential", "EC_current"):
            ec.create_dataset(name, data=np.arange(state_count, dtype=np.float64))
        for state in range(1, state_count + 1):
            group = handle.create_group(f"State_{state}")
            frequency = group.create_group("200kHz_5cycles")
            frequency.attrs["fs"] = 1_000_000.0
            for actuator in range(1, 5):
                actuator_group = frequency.create_group(f"Actionneur{actuator}")
                actuator_group.create_dataset("measured_data_rep_1.mat", data=np.ones((5, 2000), dtype=np.float64))


class MechanismV24FinalTests(unittest.TestCase):
    def test_final_protocol_has_fresh_morpho_and_coqtel_mappings(self) -> None:
        protocol, _ = load_v24_protocol("protocols/mechanism_v2_4.json")
        manifest, _ = load_v24_manifest("protocols/mechanism_v2_4_data_manifest.json")
        self.assertEqual(protocol["protocol_id"], "mechanism-v2.4")
        self.assertEqual(set(protocol["external_schema_mappings"]), {"morpho_fod7", "coqtel_corrosion"})
        roles = {item["dataset_id"]: item["role"] for item in manifest["data_sets"]}
        self.assertEqual(roles["ogw_cfrp_temperature_dam_d04"], "mechanism_discovery_only")
        self.assertEqual(roles["ogw_cfrp_temperature_dam_d24"], "mechanism_discovery_only")
        self.assertEqual(roles["morpho_fod7"], "primary_external_confirmation")

    def test_morpho_metadata_gate_never_dereferences_values(self) -> None:
        mapping = _morpho_mapping()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "morpho.h5"
            _write_morpho_fixture(source, mapping)
            with patch.object(h5py.Dataset, "__getitem__", side_effect=AssertionError("dataset values are forbidden")) as dataset_getitem, patch.object(
                h5py.AttributeManager, "__getitem__", side_effect=AssertionError("attribute values are forbidden")
            ) as attribute_getitem:
                result = audit_morpho_fod7(source, mapping)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(dataset_getitem.call_count, 0)
            self.assertEqual(attribute_getitem.call_count, 0)
            self.assertFalse(result["waveform_values_read"])
            self.assertEqual(result["component_topology"]["waveform_component_count"], 6)

    def test_morpho_metadata_gate_rejects_missing_repeat_component(self) -> None:
        mapping = _morpho_mapping()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "morpho-missing-repeat.h5"
            _write_morpho_fixture(source, mapping, omit_repeat=True)
            result = audit_morpho_fod7(source, mapping)
        self.assertEqual(result["status"], "failed")
        self.assertIn("topology", result["reason"])

    def test_coqtel_gate_never_dereferences_values_and_requires_two_campaigns(self) -> None:
        protocol, _ = load_v24_protocol("protocols/mechanism_v2_4.json")
        mapping = external_mapping(protocol, "coqtel_corrosion")
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "Essai_Corrosion1.h5"
            second = Path(directory) / "Essai_Corrosion2.h5"
            _write_coqtel_fixture(first, 2)
            _write_coqtel_fixture(second, 3)
            with patch.object(h5py.Dataset, "__getitem__", side_effect=AssertionError("dataset values are forbidden")) as dataset_getitem, patch.object(
                h5py.AttributeManager, "__getitem__", side_effect=AssertionError("attribute values are forbidden")
            ) as attribute_getitem:
                result = audit_coqtel_corrosion([first, second], mapping)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(dataset_getitem.call_count, 0)
            self.assertEqual(attribute_getitem.call_count, 0)
            self.assertEqual(len(result["campaigns"]), 2)
            self.assertEqual(result["binary_scoring_eligibility"], "metadata_schema_pass_only_no_official_binary_cutpoint_frozen")

    def test_v24_e9_defaults_are_disjoint_from_historical_namespaces(self) -> None:
        with patch.object(sys, "argv", ["e9_mechanism_v2_4_ogw.py", "--condition", "D12", "--confirmation-receipt", "results/source.json"]):
            args = e9_mechanism_v2_4_ogw.parse_args()
        self.assertEqual(args.cache_dir.name, "mechanism_v2_4_ogw_d12")
        self.assertEqual(args.output.name, "mechanism_v2_4_ogw_d12_confirmation.json")
        self.assertEqual(args.calibration_receipt.name, "mechanism_v2_4_ogw_udam_calibration_binding.json")


if __name__ == "__main__":
    unittest.main()
