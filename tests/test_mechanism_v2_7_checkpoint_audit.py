"""Independent read-only checks for synthetic mechanism-v2.7 checkpoint audits."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.experiments import mechanism_v2_7_checkpoint as checkpoint
from src.experiments.audit_mechanism_v2_7_checkpoint import (
    MechanismV27CheckpointAuditError,
    audit_checkpoint_file,
    audit_checkpoint_payload,
)


def _binding() -> checkpoint.AttemptBinding:
    return checkpoint.AttemptBinding(
        freeze_sha256="a" * 64,
        source_sha256="b" * 64,
        code_sha256="c" * 64,
    )


class MechanismV27CheckpointAuditTests(unittest.TestCase):
    def _ledger(self, directory: Path) -> tuple[Path, checkpoint.AttemptBinding, dict]:
        path = directory / "synthetic-ledger.json"
        binding = _binding()
        created = checkpoint.create_attempt(
            path,
            attempt_id="synthetic-checkpoint-audit",
            binding=binding,
            started_at_utc="2026-08-05T00:00:00Z",
        )
        return path, binding, created

    def test_audits_a_valid_unlocked_ledger_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._ledger(Path(raw_directory))
            before = path.read_bytes()
            audited = audit_checkpoint_file(path, expected_binding=binding.as_dict())
            self.assertEqual(audited["ledger_sha256"], created["ledger_sha256"])
            self.assertEqual(path.read_bytes(), before)

    def test_rejects_active_writer_sidecar_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._ledger(Path(raw_directory))
            with checkpoint.writer_lease(
                path,
                binding=binding,
                expected_ledger_sha256=created["ledger_sha256"],
                writer_id="synthetic-audited-writer",
            ):
                with self.assertRaisesRegex(MechanismV27CheckpointAuditError, "writer lease sidecar"):
                    audit_checkpoint_file(path)
                self.assertEqual(
                    audit_checkpoint_file(path, require_unlocked=False)["attempt_id"],
                    "synthetic-checkpoint-audit",
                )

    def test_rejects_timestamp_tamper_even_when_resealed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, _, _ = self._ledger(Path(raw_directory))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["entries"][0]["recorded_at_utc"] = "2026-08-05T00:00:00+00:00"
            payload["entries"][0]["entry_sha256"] = checkpoint._json_sha256(
                checkpoint._without_field(payload["entries"][0], "entry_sha256")
            )
            payload = checkpoint._seal_document(payload)
            with self.assertRaisesRegex(MechanismV27CheckpointAuditError, "ISO-8601 UTC"):
                audit_checkpoint_payload(payload)


if __name__ == "__main__":
    unittest.main()
