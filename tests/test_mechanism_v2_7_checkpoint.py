"""Synthetic-only checks for the mechanism-v2.7 checkpoint ledger."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.experiments import mechanism_v2_7_checkpoint as checkpoint


def _digest(character: str) -> str:
    return character * 64


def _binding(*, freeze: str = "a", source: str = "b", code: str = "c") -> checkpoint.AttemptBinding:
    return checkpoint.AttemptBinding(
        freeze_sha256=_digest(freeze),
        source_sha256=_digest(source),
        code_sha256=_digest(code),
    )


class MechanismV27CheckpointTests(unittest.TestCase):
    def _create(self, directory: Path) -> tuple[Path, checkpoint.AttemptBinding, dict]:
        path = directory / "synthetic-ledger.json"
        binding = _binding()
        created = checkpoint.create_attempt(
            path,
            attempt_id="synthetic-v2.7-attempt-001",
            binding=binding,
            metadata={"scope": "synthetic-only", "waveform_values_read": False},
            started_at_utc="2026-08-05T00:00:00Z",
        )
        return path, binding, created

    def test_hash_chain_and_matching_resume(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            with checkpoint.writer_lease(
                path,
                binding=binding,
                expected_ledger_sha256=created["ledger_sha256"],
                writer_id="synthetic-runner-a",
                acquired_at_utc="2026-08-05T00:00:30Z",
            ) as lease:
                first = checkpoint.append_checkpoint(
                    path,
                    binding=binding,
                    checkpoint_id="grid-00",
                    payload={"synthetic_cell": [0, 0], "status": "complete"},
                    recorded_at_utc="2026-08-05T00:01:00Z",
                    expected_ledger_sha256=created["ledger_sha256"],
                    lease=lease,
                )
                second = checkpoint.append_checkpoint(
                    path,
                    binding=binding,
                    checkpoint_id="grid-01",
                    payload={"synthetic_cell": [0, 1], "status": "complete"},
                    recorded_at_utc="2026-08-05T00:02:00Z",
                    expected_ledger_sha256=first["ledger_sha256"],
                    lease=lease,
                )
            resumed = checkpoint.resume_attempt(
                path, binding=binding, expected_ledger_sha256=second["ledger_sha256"]
            )

        self.assertEqual(resumed, second)
        self.assertEqual(resumed["state"], checkpoint.ACTIVE_STATE)
        self.assertEqual([entry["sequence"] for entry in resumed["entries"]], [0, 1, 2])
        self.assertEqual(resumed["entries"][0]["previous_entry_sha256"], checkpoint.GENESIS_PREVIOUS_SHA256)
        self.assertEqual(resumed["entries"][2]["previous_entry_sha256"], resumed["entries"][1]["entry_sha256"])
        self.assertEqual([entry["checkpoint_id"] for entry in resumed["entries"][1:]], ["grid-00", "grid-01"])

    def test_resume_rejects_any_changed_freeze_source_or_code_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            mismatches = (
                _binding(freeze="d"),
                _binding(source="d"),
                _binding(code="d"),
            )
            for mismatch in mismatches:
                with self.subTest(mismatch=mismatch):
                    with self.assertRaises(checkpoint.CheckpointLedgerError):
                        checkpoint.resume_attempt(
                            path, binding=mismatch, expected_ledger_sha256=created["ledger_sha256"]
                        )
            self.assertEqual(
                checkpoint.resume_attempt(
                    path, binding=binding, expected_ledger_sha256=created["ledger_sha256"]
                )["attempt_id"],
                "synthetic-v2.7-attempt-001",
            )

    def test_single_attempt_and_terminal_state_reject_resume_and_updates(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            with self.assertRaises(checkpoint.CheckpointLedgerError):
                checkpoint.create_attempt(path, attempt_id="second-attempt", binding=binding)
            with checkpoint.writer_lease(
                path,
                binding=binding,
                expected_ledger_sha256=created["ledger_sha256"],
                writer_id="synthetic-runner-terminal",
            ) as lease:
                terminal = checkpoint.finalize_attempt(
                    path,
                    binding=binding,
                    terminal_state="invalidated",
                    payload={"reason": "synthetic stop"},
                    recorded_at_utc="2026-08-05T00:03:00Z",
                    expected_ledger_sha256=created["ledger_sha256"],
                    lease=lease,
                )
                self.assertEqual(terminal["state"], "invalidated")
                with self.assertRaises(checkpoint.CheckpointLedgerError):
                    checkpoint.append_checkpoint(
                        path,
                        binding=binding,
                        checkpoint_id="late",
                        expected_ledger_sha256=terminal["ledger_sha256"],
                        lease=lease,
                    )
            with self.assertRaises(checkpoint.CheckpointLedgerError):
                checkpoint.resume_attempt(
                    path, binding=binding, expected_ledger_sha256=terminal["ledger_sha256"]
                )

    def test_tamper_is_rejected_before_resume(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            document = json.loads(path.read_text(encoding="utf-8"))
            document["entries"][0]["payload"]["metadata"]["scope"] = "tampered"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(checkpoint.CheckpointLedgerError):
                checkpoint.resume_attempt(
                    path, binding=binding, expected_ledger_sha256=created["ledger_sha256"]
                )

    def test_writer_lease_blocks_a_second_writer_and_pins_the_head(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            with checkpoint.writer_lease(
                path,
                binding=binding,
                expected_ledger_sha256=created["ledger_sha256"],
                writer_id="synthetic-runner-a",
                acquired_at_utc="2026-08-05T00:00:30Z",
            ) as lease:
                with self.assertRaisesRegex(checkpoint.CheckpointLedgerError, "writer lease already exists"):
                    checkpoint.acquire_writer_lease(
                        path,
                        binding=binding,
                        expected_ledger_sha256=created["ledger_sha256"],
                        writer_id="synthetic-runner-b",
                    )
                with self.assertRaisesRegex(checkpoint.CheckpointLedgerError, "writer lease exists"):
                    checkpoint.resume_attempt(
                        path, binding=binding, expected_ledger_sha256=created["ledger_sha256"]
                    )
                first = checkpoint.append_checkpoint(
                    path,
                    binding=binding,
                    checkpoint_id="grid-00",
                    recorded_at_utc="2026-08-05T00:01:00Z",
                    expected_ledger_sha256=created["ledger_sha256"],
                    lease=lease,
                )
                with self.assertRaisesRegex(checkpoint.CheckpointLedgerError, "expected head"):
                    checkpoint.append_checkpoint(
                        path,
                        binding=binding,
                        checkpoint_id="grid-01",
                        recorded_at_utc="2026-08-05T00:02:00Z",
                        expected_ledger_sha256=created["ledger_sha256"],
                        lease=lease,
                    )
            self.assertFalse(lease.lock_path.exists())
            self.assertEqual(
                checkpoint.resume_attempt(
                    path, binding=binding, expected_ledger_sha256=first["ledger_sha256"]
                )["ledger_sha256"],
                first["ledger_sha256"],
            )

    def test_timestamp_validation_rejects_invalid_and_nonmonotonic_updates(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            with self.assertRaisesRegex(checkpoint.CheckpointLedgerError, "ISO-8601 UTC"):
                checkpoint.create_attempt(
                    Path(raw_directory) / "bad-time.json",
                    attempt_id="synthetic-bad-time",
                    binding=binding,
                    started_at_utc="2026-08-05T00:00:00+00:00",
                )
            with checkpoint.writer_lease(
                path,
                binding=binding,
                expected_ledger_sha256=created["ledger_sha256"],
                writer_id="synthetic-runner-time",
            ) as lease:
                with self.assertRaisesRegex(checkpoint.CheckpointLedgerError, "strictly increasing"):
                    checkpoint.append_checkpoint(
                        path,
                        binding=binding,
                        checkpoint_id="same-time",
                        recorded_at_utc="2026-08-05T00:00:00Z",
                        expected_ledger_sha256=created["ledger_sha256"],
                        lease=lease,
                    )
                with self.assertRaisesRegex(checkpoint.CheckpointLedgerError, "ISO-8601 UTC"):
                    checkpoint.append_checkpoint(
                        path,
                        binding=binding,
                        checkpoint_id="offset-time",
                        recorded_at_utc="2026-08-05T00:01:00+00:00",
                        expected_ledger_sha256=created["ledger_sha256"],
                        lease=lease,
                    )
            self.assertEqual(checkpoint.verify_ledger(path)["ledger_sha256"], created["ledger_sha256"])

    def test_failed_atomic_replace_preserves_last_valid_ledger_and_cleans_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            path, binding, created = self._create(directory)
            before = path.read_bytes()
            with checkpoint.writer_lease(
                path,
                binding=binding,
                expected_ledger_sha256=created["ledger_sha256"],
                writer_id="synthetic-runner-failure",
            ) as lease:
                with patch.object(checkpoint.os, "replace", side_effect=OSError("synthetic replace failure")):
                    with self.assertRaises(OSError):
                        checkpoint.append_checkpoint(
                            path,
                            binding=binding,
                            checkpoint_id="grid-00",
                            expected_ledger_sha256=created["ledger_sha256"],
                            lease=lease,
                        )
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(directory.glob(f".{path.name}.*.tmp")), [])
            self.assertEqual(
                checkpoint.resume_attempt(
                    path, binding=binding, expected_ledger_sha256=created["ledger_sha256"]
                )["state"],
                checkpoint.ACTIVE_STATE,
            )


if __name__ == "__main__":
    unittest.main()
