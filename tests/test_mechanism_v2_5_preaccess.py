"""Synthetic, no-real-data checks for the mechanism-v2.5 freeze boundary."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np

from src.data.mechanism_v2_5_external_schema import audit_morpho_fod7
from src.experiments import audit_mechanism_v2_5 as external_audit
from src.experiments import e9_mechanism_v2_5_morpho as morpho
from src.experiments.mechanism_v2_5_successor import (
    external_execution_contract, external_mapping, load_v25_manifest, load_v25_protocol,
)
from src.methods.mechanism_v2 import control_injection_grid
from src.methods.strict_codecs import SodTransitionCodec


def _small_mapping() -> dict:
    protocol, _ = load_v25_protocol("protocols/mechanism_v2_5.json")
    mapping = external_mapping(protocol, "morpho_fod7")
    mapping.update({
        "baseline_blocks": ["Healthy_Clamped", "Healthy_Unclamped"],
        "fatigue_blocks_order": ["4kN_200"],
        "excluded_active_blocks": ["AfterImpact_Clamped"],
        "frequency_values": ["100kHz"],
        "actuator_ids": [1],
        "repeat_ids": [1, 2],
    })
    return mapping


def _write_morpho_fixture(path: Path, mapping: dict, *, omit_repeat: bool = False) -> None:
    with h5py.File(path, "w") as handle:
        root = handle.create_group("5_Active")
        for block in mapping["baseline_blocks"] + mapping["fatigue_blocks_order"] + mapping["excluded_active_blocks"]:
            block_group = root.create_group(block)
            block_group.attrs["Status"] = "synthetic"
            frequency = block_group.create_group("100kHz")
            frequency.attrs["fs"] = 1_000_000.0
            actuator = frequency.create_group("Actionneur1")
            repeats = [1] if omit_repeat and block == "4kN_200" else [1, 2]
            for repeat in repeats:
                actuator.create_dataset(f"measured_data_rep_{repeat}.mat", data=np.ones((30, 5001), dtype=np.float64))


class MechanismV25PreaccessTests(unittest.TestCase):
    def test_v25_protocol_and_manifest_keep_roles_and_runner_contract(self) -> None:
        protocol, _ = load_v25_protocol("protocols/mechanism_v2_5.json")
        manifest, _ = load_v25_manifest("protocols/mechanism_v2_5_data_manifest.json")
        self.assertEqual(protocol["protocol_id"], "mechanism-v2.5")
        self.assertEqual(protocol["external_execution_contract"]["source_dataset_id"], "morpho_fod7")
        self.assertEqual(protocol["external_execution_contract"]["group_split"]["unit_of_analysis"], "fatigue_baseline_block")
        roles = {item["dataset_id"]: item["role"] for item in manifest["data_sets"]}
        self.assertEqual(roles["ogw_cfrp_temperature_dam_d04"], "mechanism_discovery_only")
        self.assertEqual(roles["ogw_cfrp_temperature_dam_d24"], "mechanism_discovery_only")
        self.assertEqual(roles["morpho_fod7"], "primary_external_confirmation")

    def test_v25_schema_gate_never_reads_dataset_or_attribute_values(self) -> None:
        mapping = _small_mapping()
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
        self.assertEqual(result["component_topology"]["component_packets_per_block"], 2)

    def test_v25_schema_gate_rejects_missing_repeat(self) -> None:
        mapping = _small_mapping()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "morpho-missing-repeat.h5"
            _write_morpho_fixture(source, mapping, omit_repeat=True)
            result = audit_morpho_fod7(source, mapping)
        self.assertEqual(result["status"], "failed")
        self.assertIn("topology", result["reason"])

    def test_component_packet_cap_probes_and_group_split_are_fixed(self) -> None:
        mapping = _small_mapping()
        keys = morpho._component_keys(mapping)
        split = morpho._group_split(mapping, keys)
        self.assertEqual(split["splits"]["fit"], ["Healthy_Clamped"])
        self.assertEqual(split["splits"]["held_out_normal"], ["Healthy_Unclamped"])
        self.assertEqual(split["splits"]["degradation"], ["4kN_200"])
        self.assertFalse(split["paths_or_repeats_are_independent_samples"])
        cap = morpho._path_cap(2048, 29)
        codec = SodTransitionCodec(delta_codes=8, signal_scale=1.0, max_path_payload_bytes=cap)
        codes = np.tile(np.arange(96, dtype=np.int16) % 32, (29, 1))
        evaluation = morpho._evaluate_packet(codes, codec, 1_000_000.0, [(2_000.0, 6_000.0)], 2)
        self.assertLessEqual(evaluation.payload_bytes, 2048)
        self.assertIn("event_times_sha256", evaluation.trace_receipt)
        probes = morpho._mechanism_probes([2048], [1, 8], 29)
        self.assertEqual(len(probes), 4)
        self.assertEqual([item for item in probes if item["proposition"] == "quantization_collision" and item["delta_codes"] == 1][0]["status"], "not_applicable")
        self.assertTrue(all(item["status"] == "passed" for item in probes if item["proposition"] == "terminal_hold"))

    def test_healthy_control_grid_uses_frozen_packet_and_receiver_selection(self) -> None:
        protocol, _ = load_v25_protocol("protocols/mechanism_v2_5.json")
        contract = copy.deepcopy(external_execution_contract(protocol))
        contract["healthy_only_fit"]["control_component_ordinals"] = [0, 1, 2]
        training = []
        for ordinal in range(3):
            packet = np.tile((np.arange(96, dtype=np.int16) + ordinal) % 64, (29, 1))
            training.append((("100kHz", 1, ordinal + 1), packet))
        controls = morpho._control_injections(training, [2048], [8], contract, protocol["healthy_control_injections"])
        expected = control_injection_grid([2048], [8], protocol["healthy_control_injections"])
        self.assertEqual({item["control_id"] for item in controls}, {item["control_id"] for item in expected})
        self.assertTrue(all(item["healthy_component_packet_ordinals"] == [0, 1, 2] for item in controls))

    def test_external_auditor_rejects_an_incomplete_grid(self) -> None:
        protocol, _ = load_v25_protocol("protocols/mechanism_v2_5.json")
        mapping = external_mapping(protocol, "morpho_fod7")
        malformed = {
            "configuration": {
                "capacity_bytes_per_record": protocol["ogw_representation_contract"]["payload_accounting"]["capacity_bytes_per_record"],
                "delta_codes": protocol["eventization_grid"]["delta_codes"],
                "event_features": protocol["eventization_grid"]["event_features"],
                "aggregation_heads": protocol["eventization_grid"]["diagnostic"]["heads"],
                "control_injection_grid_sha256": __import__("src.experiments.mechanism_v2_5_successor", fromlist=["json_hash"]).json_hash(control_injection_grid(protocol["ogw_representation_contract"]["payload_accounting"]["capacity_bytes_per_record"], protocol["eventization_grid"]["delta_codes"], protocol["healthy_control_injections"])),
            },
            "grid_results": [],
        }
        with self.assertRaises(external_audit.AuditError):
            external_audit._audit_grid(malformed, protocol, mapping)


if __name__ == "__main__":
    unittest.main()
