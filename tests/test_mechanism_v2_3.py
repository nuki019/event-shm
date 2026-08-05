"""Pre-freeze regression checks for the mechanism-v2.3 successor wiring."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from src.experiments import audit_mechanism_v2_3, e9_mechanism_v2_3_ogw
from src.experiments.mechanism_v2_3_successor import load_successor_manifest, load_successor_protocol


class MechanismV23Tests(unittest.TestCase):
    def test_v23_overlay_redeclares_the_pre_access_coqtel_mapping(self) -> None:
        protocol, overlay = load_successor_protocol("protocols/mechanism_v2_3.json")
        manifest, manifest_overlay = load_successor_manifest("protocols/mechanism_v2_3_data_manifest.json")
        mapping = protocol["external_schema_mappings"]["coqtel_corrosion"]
        self.assertEqual(protocol["protocol_id"], "mechanism-v2.3")
        self.assertEqual(mapping["mapping_id"], "mechanism-v2.3-coqtel-hierarchical-schema-v1")
        self.assertEqual(overlay["predecessor_invalidation"]["receipt_path"], "protocols/mechanism_v2_2_invalidation_receipt.json")
        self.assertEqual(manifest_overlay["predecessor_invalidation"], overlay["predecessor_invalidation"])
        self.assertTrue(any(entry["dataset_id"] == "coqtel_corrosion" for entry in manifest["data_sets"]))

    def test_v23_wrappers_default_to_disjoint_cache_and_receipt_namespaces(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["e9_mechanism_v2_3_ogw.py", "--condition", "D12", "--confirmation-receipt", "results/example.json"],
        ):
            e9_args = e9_mechanism_v2_3_ogw.parse_args()
        self.assertEqual(e9_args.cache_dir, Path("D:/event-camera/SHM/data/interim/mechanism_v2_3_ogw_d12"))
        self.assertEqual(e9_args.output, Path("D:/event-camera/SHM/results/mechanism_v2_3_ogw_d12_confirmation.json"))
        with patch.object(sys, "argv", ["audit_mechanism_v2_3.py", "--result", "results/example.json"]):
            audit_args = audit_mechanism_v2_3.parse_args()
        self.assertEqual(audit_args.protocol.name, "mechanism_v2_3.json")
        self.assertEqual(audit_args.manifest.name, "mechanism_v2_3_data_manifest.json")
        self.assertEqual(audit_args.freeze_receipt.name, "mechanism_v2_3_freeze_receipt.json")


if __name__ == "__main__":
    unittest.main()
