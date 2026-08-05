"""Regression checks for the document-only MORPHO semantic-discovery boundary."""

from __future__ import annotations

import unittest

from src.experiments.mechanism_v2_4_morpho_semantic_discovery import load_semantic_protocol, validate_semantic_provenance


class MorphoSemanticDiscoveryTests(unittest.TestCase):
    def test_semantic_protocol_is_pinned_to_no_value_structural_discovery(self) -> None:
        protocol, _ = load_semantic_protocol("protocols/mechanism_v2_4_morpho_semantic_discovery.json")
        structural_path, structural_result, documents = validate_semantic_provenance(protocol)
        self.assertEqual(structural_path.name, "mechanism_v2_4_morpho_metadata_discovery.json")
        self.assertEqual(structural_result["access_receipt"]["waveform_values_read"], False)
        self.assertEqual(set(documents), {"readme_pdf", "reader_example"})
        self.assertEqual(documents["readme_pdf"].name, "ReadMe.pdf")
        self.assertEqual(documents["reader_example"].name, "EXAMPLE_READ_DATA.m")


if __name__ == "__main__":
    unittest.main()
