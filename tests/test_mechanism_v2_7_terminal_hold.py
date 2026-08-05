"""Unit tests for the synthetic-only mechanism-v2.7 terminal-hold basis."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.experiments import test_mechanism_v2_7_terminal_hold as terminal_hold


class MechanismV27TerminalHoldTests(unittest.TestCase):
    def test_parameterized_grid_emits_auditable_two_trajectory_evidence(self) -> None:
        before = datetime.now(timezone.utc)
        result = terminal_hold.run_terminal_hold_preaccess_test(
            n_paths=2,
            n_samples=96,
            capacities=[64, 96],
            deltas=[1, 8, 64],
        )
        after = datetime.now(timezone.utc)

        self.assertEqual(result["runner_id"], terminal_hold.RUNNER_ID)
        observed_utc = datetime.fromisoformat(result["generated_at_utc"].replace("Z", "+00:00"))
        self.assertGreaterEqual(observed_utc, before)
        self.assertLessEqual(observed_utc, after)
        self.assertEqual(result["data_access"], {
            "mode": "synthetic_only",
            "real_waveform_accessed": False,
            "real_waveform_paths": [],
            "synthetic_input_construction": "alternating integer-code levels with a post-cap divergent suffix",
        })
        self.assertEqual(result["inputs"], {
            "n_paths": 2,
            "n_samples": 96,
            "capacities_bytes": [64, 96],
            "delta_codes": [1, 8, 64],
        })
        self.assertEqual(result["grid_coverage"], {
            "expected_cells": 6,
            "observed_cells": 6,
            "passed_cells": 6,
            "not_applicable_cells": 0,
            "failed_cells": 0,
        })
        self.assertTrue(result["passed"])
        self.assertTrue(result["preaccess_ready"])
        self.assertEqual(
            result["code_hashes"]["runner_sha256"],
            hashlib.sha256(Path(terminal_hold.__file__).read_bytes()).hexdigest(),
        )

        for cell in result["cells"]:
            self.assertTrue(cell["applicable"])
            self.assertEqual(cell["status"], "passed")
            self.assertTrue(cell["first_cap_saturated"])
            self.assertTrue(cell["second_cap_saturated"])
            self.assertTrue(cell["first_has_terminal_hold"])
            self.assertTrue(cell["second_has_terminal_hold"])
            self.assertTrue(cell["same_serialized_payload"])
            self.assertTrue(cell["same_payload_sha256"])
            self.assertTrue(cell["same_decoded_output"])
            self.assertTrue(cell["same_decoded_sha256"])
            self.assertTrue(cell["input_trajectories_differ"])
            self.assertIsNotNone(cell["first_blocked_event_index"])
            self.assertNotEqual(cell["first_trace"]["source_codes_sha256"], cell["second_trace"]["source_codes_sha256"])
            self.assertEqual(cell["first_trace"]["payload_sha256"], cell["second_trace"]["payload_sha256"])
            self.assertEqual(cell["first_trace"]["decoded_codes_sha256"], cell["second_trace"]["decoded_codes_sha256"])

    def test_insufficient_samples_is_explicitly_not_applicable_and_not_ready(self) -> None:
        result = terminal_hold.run_terminal_hold_preaccess_test(
            n_paths=1,
            n_samples=8,
            capacities=[4096],
            deltas=[1],
        )

        self.assertTrue(result["passed"])
        self.assertFalse(result["preaccess_ready"])
        self.assertEqual(result["grid_coverage"]["not_applicable_cells"], 1)
        cell = result["cells"][0]
        self.assertFalse(cell["applicable"])
        self.assertEqual(cell["status"], "not_applicable")
        self.assertEqual(cell["reason"], "n_samples_insufficient_to_saturate_per_path_cap")
        self.assertFalse(cell["first_cap_saturated"])
        self.assertIsNone(cell["second_cap_saturated"])
        self.assertIsNotNone(cell["first_trace"])

    def test_out_of_range_delta_is_explicitly_not_applicable(self) -> None:
        result = terminal_hold.run_terminal_hold_preaccess_test(
            n_paths=1,
            n_samples=96,
            capacities=[64],
            deltas=[32768],
        )

        cell = result["cells"][0]
        self.assertTrue(result["passed"])
        self.assertFalse(result["preaccess_ready"])
        self.assertFalse(cell["applicable"])
        self.assertIn("delta_outside_int16_dynamic_range", cell["reason"])
        self.assertIsNone(cell["first_trace"])

    def test_optional_receipt_write_is_json_and_does_not_need_a_protocol(self) -> None:
        result = terminal_hold.run_terminal_hold_preaccess_test(
            n_paths=2,
            n_samples=96,
            capacities=[64],
            deltas=[8],
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "synthetic_terminal_hold.json"
            terminal_hold.write_audit_result(result, output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), result)

    def test_grid_inputs_reject_duplicates_before_any_trace_is_built(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            terminal_hold.run_terminal_hold_preaccess_test(
                n_paths=2,
                n_samples=96,
                capacities=[64, 64],
                deltas=[8],
            )


if __name__ == "__main__":
    unittest.main()
