"""Independent read-only checks for synthetic mechanism-v2.7 checkpoint audits."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.experiments import mechanism_v2_7_checkpoint as checkpoint
from src.experiments.audit_mechanism_v2_7_checkpoint import (
    MechanismV27CheckpointAuditError,
    audit_checkpoint_file,
    audit_checkpoint_payload,
)


class _SyntheticHeadAnchorAuthority:
    """Fixture authority; it is never a production immutable anchor."""

    def __init__(self, expectation: checkpoint.CheckpointHeadExpectation) -> None:
        self.expected = expectation

    def verify_head(self, expectation: checkpoint.CheckpointHeadExpectation) -> bool:
        return expectation == self.expected


def _binding() -> checkpoint.AttemptBinding:
    return checkpoint.AttemptBinding(
        freeze_sha256="a" * 64,
        source_sha256="b" * 64,
        code_sha256="c" * 64,
    )


def _authorization(
    binding: checkpoint.AttemptBinding, document: dict
) -> tuple[checkpoint.CheckpointHeadExpectation, _SyntheticHeadAnchorAuthority]:
    expectation = checkpoint.CheckpointHeadExpectation(
        attempt_id=document["attempt_id"],
        binding=binding,
        ledger_sha256=document["ledger_sha256"],
        anchor_id=f"synthetic://checkpoint/{document['attempt_id']}",
        anchor_sha256="e" * 64,
    )
    return expectation, _SyntheticHeadAnchorAuthority(expectation)


class MechanismV27CheckpointAuditTests(unittest.TestCase):
    def _ledger(
        self, directory: Path
    ) -> tuple[
        Path,
        checkpoint.AttemptBinding,
        dict,
        checkpoint.CheckpointHeadExpectation,
        _SyntheticHeadAnchorAuthority,
    ]:
        path = directory / "synthetic-ledger.json"
        binding = _binding()
        created = checkpoint.create_attempt(
            path,
            attempt_id="synthetic-checkpoint-audit",
            binding=binding,
            started_at_utc="2026-08-05T00:00:00Z",
        )
        start_expectation, start_authority = _authorization(binding, created)
        with checkpoint.writer_lease(
            path,
            expectation=start_expectation,
            anchor_authority=start_authority,
            writer_id="synthetic-checkpoint-auditor",
            acquired_at_utc="2026-08-05T00:00:30Z",
        ) as lease:
            terminal = checkpoint.finalize_attempt(
                path,
                binding=binding,
                terminal_state="completed",
                payload={"scope": "synthetic-only"},
                recorded_at_utc="2026-08-05T00:01:00Z",
                expected_ledger_sha256=created["ledger_sha256"],
                lease=lease,
            )
        expectation, authority = _authorization(binding, terminal)
        return path, binding, terminal, expectation, authority

    def test_audits_a_terminal_unlocked_ledger_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, _, terminal, expectation, authority = self._ledger(Path(raw_directory))
            before = path.read_bytes()
            audited = audit_checkpoint_file(
                path,
                expectation=expectation,
                anchor_authority=authority,
            )
            self.assertEqual(audited["ledger_sha256"], terminal["ledger_sha256"])
            self.assertEqual(audited["state"], "completed")
            self.assertEqual(path.read_bytes(), before)

    def test_auditor_opens_the_os_gate_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, _, _, expectation, authority = self._ledger(Path(raw_directory))
            original_open = checkpoint.os.open
            calls: list[tuple[str, int]] = []

            def capture_open(path_arg: str, flags: int, *args: object) -> int:
                calls.append((str(path_arg), flags))
                return original_open(path_arg, flags, *args)

            with patch.object(checkpoint.os, "open", side_effect=capture_open):
                audit_checkpoint_file(
                    path,
                    expectation=expectation,
                    anchor_authority=authority,
                )
            gate_flags = [
                flags
                for opened_path, flags in calls
                if opened_path == str(checkpoint._gate_path(path))
            ]
            self.assertEqual(len(gate_flags), 1)
            access_mode = getattr(checkpoint.os, "O_ACCMODE", 3)
            self.assertEqual(gate_flags[0] & access_mode, checkpoint.os.O_RDONLY)

    def test_rejects_active_writer_before_any_snapshot_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            path = directory / "synthetic-ledger.json"
            binding = _binding()
            created = checkpoint.create_attempt(
                path,
                attempt_id="synthetic-active-checkpoint-audit",
                binding=binding,
                started_at_utc="2026-08-05T00:00:00Z",
            )
            expectation, authority = _authorization(binding, created)
            with checkpoint.writer_lease(
                path,
                expectation=expectation,
                anchor_authority=authority,
                writer_id="synthetic-active-writer",
            ):
                with self.assertRaisesRegex(MechanismV27CheckpointAuditError, "checkpoint gate"):
                    audit_checkpoint_file(
                        path,
                        expectation=expectation,
                        anchor_authority=authority,
                    )

    def test_rejects_timestamp_tamper_even_when_resealed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, _, expectation, _ = self._ledger(Path(raw_directory))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["entries"][0]["recorded_at_utc"] = "2026-08-05T00:00:00+00:00"
            payload["entries"][0]["entry_sha256"] = checkpoint._json_sha256(
                checkpoint._without_field(payload["entries"][0], "entry_sha256")
            )
            payload = checkpoint._seal_document(payload)
            resealed_expectation = checkpoint.CheckpointHeadExpectation(
                attempt_id=expectation.attempt_id,
                binding=binding,
                ledger_sha256=payload["ledger_sha256"],
                anchor_id="synthetic://checkpoint/resealed-timestamp-tamper",
                anchor_sha256="e" * 64,
            )
            with self.assertRaisesRegex(MechanismV27CheckpointAuditError, "ISO-8601 UTC"):
                audit_checkpoint_payload(
                    payload,
                    expectation=resealed_expectation,
                    anchor_authority=_SyntheticHeadAnchorAuthority(resealed_expectation),
                )

    def test_rejects_wrong_expected_head_even_with_a_matching_test_authority(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            _, binding, terminal, _, _ = self._ledger(Path(raw_directory))
            wrong_expectation = checkpoint.CheckpointHeadExpectation(
                attempt_id=terminal["attempt_id"],
                binding=binding,
                ledger_sha256="f" * 64,
                anchor_id="synthetic://checkpoint/wrong-head",
                anchor_sha256="e" * 64,
            )
            with self.assertRaisesRegex(MechanismV27CheckpointAuditError, "expected head"):
                audit_checkpoint_payload(
                    terminal,
                    expectation=wrong_expectation,
                    anchor_authority=_SyntheticHeadAnchorAuthority(wrong_expectation),
                )

    def test_refuses_a_missing_or_nonverifying_anchor_authority(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            _, _, terminal, expectation, _ = self._ledger(Path(raw_directory))
            with self.assertRaisesRegex(MechanismV27CheckpointAuditError, "HeadAnchorAuthority"):
                audit_checkpoint_payload(
                    terminal,
                    expectation=expectation,
                    anchor_authority=object(),
                )


if __name__ == "__main__":
    unittest.main()
