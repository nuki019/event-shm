"""Tests for the synthetic-only mechanism-v2.7 pre-access auditor."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.experiments.audit_mechanism_v2_7 import (
    MechanismV27AuditError,
    audit_synthetic_envelope,
)
from src.experiments.mechanism_v2_7_contract import (
    CAPACITIES,
    CONTRACT_ID,
    DELTAS,
    PROTOCOL_ID,
    RESULT_KIND,
    canonical_sha256,
    seal_result_envelope,
)


def _fixture() -> dict:
    grid = []
    for capacity in CAPACITIES:
        for delta in DELTAS:
            grid.append(
                {
                    "capacity_bytes": capacity,
                    "delta_codes": delta,
                    "status": "synthetic_scored",
                    "payload_bytes_per_record": capacity - (delta % 13),
                    "event_count": delta % 31,
                    "cap_saturated": delta >= 8192,
                    "synthetic_trace_sha256": canonical_sha256({"capacity": capacity, "delta": delta}),
                }
            )
    return seal_result_envelope(
        {
            "contract_id": CONTRACT_ID,
            "protocol_id": PROTOCOL_ID,
            "result_kind": RESULT_KIND,
            "run_id": "v27-audit-fixture",
            "authorization_not_before_utc": "2026-08-05T10:00:00Z",
            "started_utc": "2026-08-05T10:01:00Z",
            "completed_utc": "2026-08-05T10:02:00Z",
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
                "generator_id": "v27-audit-fixture",
                "seed": 7,
                "input_sha256": canonical_sha256({"fixture": "audit", "seed": 7}),
            },
            "grid": grid,
        }
    )


class MechanismV27AuditTests(unittest.TestCase):
    def test_audits_valid_synthetic_envelope(self) -> None:
        result = audit_synthetic_envelope(_fixture(), not_before_utc="2026-08-05T10:00:00Z")
        self.assertEqual(result["run_id"], "v27-audit-fixture")

    def test_rejects_post_contact_or_prior_data(self) -> None:
        with self.assertRaisesRegex(MechanismV27AuditError, "not pre-contact"):
            audit_synthetic_envelope(_fixture(), data_contacted_utc="2026-08-05T10:02:00Z")

        result = _fixture()
        result["data_access"]["contacted_dataset_ids"] = ["morpho_fod7"]
        result = seal_result_envelope(result)
        with self.assertRaisesRegex(MechanismV27AuditError, "contacted_dataset_ids"):
            audit_synthetic_envelope(result)

    def test_payload_audit_never_opens_files(self) -> None:
        with patch("builtins.open", side_effect=AssertionError("filesystem access is forbidden")):
            result = audit_synthetic_envelope(_fixture())
        self.assertEqual(len(result["grid"]), 32)


if __name__ == "__main__":
    unittest.main()
