"""Synthetic-only tests for the mechanism-v2.7 canonical result contract."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.experiments.mechanism_v2_7_contract import (
    CAPACITIES,
    DELTAS,
    CONTRACT_ID,
    MechanismV27ContractError,
    PROTOCOL_ID,
    RESULT_KIND,
    canonical_sha256,
    seal_result_envelope,
    validate_result_envelope,
)


def _valid_envelope() -> dict:
    grid = []
    for capacity in CAPACITIES:
        for delta in DELTAS:
            grid.append(
                {
                    "capacity_bytes": capacity,
                    "delta_codes": delta,
                    "status": "synthetic_scored",
                    "payload_bytes_per_record": float(capacity - (delta % 17)),
                    "event_count": delta % 97,
                    "cap_saturated": delta >= 8192,
                    "synthetic_trace_sha256": canonical_sha256(
                        {"fixture": "v2.7", "capacity": capacity, "delta": delta}
                    ),
                }
            )
    return seal_result_envelope(
        {
            "contract_id": CONTRACT_ID,
            "protocol_id": PROTOCOL_ID,
            "result_kind": RESULT_KIND,
            "run_id": "v27-synthetic-contract-smoke",
            "authorization_not_before_utc": "2026-08-05T09:00:00Z",
            "started_utc": "2026-08-05T09:01:00Z",
            "completed_utc": "2026-08-05T09:02:00Z",
            "data_access": {
                "mode": "synthetic_only",
                "real_waveform_accessed": False,
                "external_data_accessed": False,
                "contacted_dataset_ids": [],
                "previously_contacted_dataset_ids": [],
                "contacted_artifact_ids": [],
                "first_real_waveform_access_utc": None,
            },
            "synthetic_input": {
                "generator_id": "v27-unit-fixture",
                "seed": 20260805,
                "input_sha256": canonical_sha256({"fixture": "v2.7", "seed": 20260805}),
            },
            "grid": grid,
        }
    )


class MechanismV27ContractTests(unittest.TestCase):
    def test_valid_synthetic_envelope_has_all_32_cells(self) -> None:
        envelope = _valid_envelope()
        checked = validate_result_envelope(envelope, not_before_utc="2026-08-05T09:00:00Z")
        self.assertEqual(len(checked["grid"]), 32)
        self.assertEqual(checked, envelope)

    def test_hashes_reject_tampering(self) -> None:
        envelope = _valid_envelope()
        envelope["grid"][0]["event_count"] += 1
        with self.assertRaisesRegex(MechanismV27ContractError, "grid_sha256"):
            validate_result_envelope(envelope)

        envelope = _valid_envelope()
        envelope["run_id"] = "v27-tampered-run"
        with self.assertRaisesRegex(MechanismV27ContractError, "envelope_sha256"):
            validate_result_envelope(envelope)

    def test_required_fields_and_complete_grid_are_enforced(self) -> None:
        envelope = _valid_envelope()
        del envelope["synthetic_input"]
        with self.assertRaisesRegex(MechanismV27ContractError, "missing synthetic_input"):
            validate_result_envelope(envelope)

        envelope = _valid_envelope()
        envelope["grid"].pop()
        envelope = seal_result_envelope(envelope)
        with self.assertRaisesRegex(MechanismV27ContractError, "32 fixed cells"):
            validate_result_envelope(envelope)

    def test_time_boundaries_reject_unauthorized_or_post_contact_results(self) -> None:
        envelope = _valid_envelope()
        envelope["started_utc"] = "2026-08-05T08:59:59Z"
        envelope = seal_result_envelope(envelope)
        with self.assertRaisesRegex(MechanismV27ContractError, "precedes authorization"):
            validate_result_envelope(envelope)

        envelope = _valid_envelope()
        with self.assertRaisesRegex(MechanismV27ContractError, "not pre-contact"):
            validate_result_envelope(envelope, data_contacted_utc="2026-08-05T09:02:00Z")

    def test_any_real_or_previous_data_contact_is_rejected(self) -> None:
        envelope = _valid_envelope()
        envelope["data_access"]["previously_contacted_dataset_ids"] = ["morpho_fod7"]
        envelope = seal_result_envelope(envelope)
        with self.assertRaisesRegex(MechanismV27ContractError, "previously_contacted_dataset_ids"):
            validate_result_envelope(envelope)

        envelope = _valid_envelope()
        envelope["data_access"]["real_waveform_accessed"] = True
        envelope = seal_result_envelope(envelope)
        with self.assertRaisesRegex(MechanismV27ContractError, "real_waveform_accessed"):
            validate_result_envelope(envelope)

    def test_validation_performs_no_filesystem_access(self) -> None:
        envelope = _valid_envelope()
        with patch("builtins.open", side_effect=AssertionError("filesystem access is forbidden")):
            checked = validate_result_envelope(envelope)
        self.assertEqual(checked["data_access"]["mode"], "synthetic_only")

    def test_caller_supplied_not_before_boundary_is_enforced(self) -> None:
        envelope = _valid_envelope()
        with self.assertRaisesRegex(MechanismV27ContractError, "caller-supplied not_before_utc"):
            validate_result_envelope(envelope, not_before_utc="2026-08-05T09:01:01Z")


if __name__ == "__main__":
    unittest.main()
