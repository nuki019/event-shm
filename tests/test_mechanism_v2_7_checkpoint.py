"""Synthetic-only checks for the mechanism-v2.7 checkpoint ledger."""

from __future__ import annotations

import json
import multiprocessing
import tempfile
import threading
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


class _SyntheticHeadAnchorAuthority:
    """Test double only; it cannot authorize a real frozen run."""

    def __init__(self, expected: checkpoint.CheckpointHeadExpectation) -> None:
        self.expected = expected

    def verify_head(self, expectation: checkpoint.CheckpointHeadExpectation) -> bool:
        return expectation == self.expected


class _AlwaysAcceptHeadAnchorAuthority:
    """Only used to prove that an OS gate blocks a separate process first."""

    def verify_head(self, expectation: checkpoint.CheckpointHeadExpectation) -> bool:
        return True


def _attempt_competing_writer(
    path_text: str,
    expectation: checkpoint.CheckpointHeadExpectation,
    result_queue: multiprocessing.queues.Queue,
) -> None:
    try:
        lease = checkpoint.acquire_writer_lease(
            Path(path_text),
            expectation=expectation,
            anchor_authority=_AlwaysAcceptHeadAnchorAuthority(),
            writer_id="synthetic-cross-process-writer",
        )
    except checkpoint.CheckpointLedgerError as error:
        result_queue.put(("blocked", str(error)))
        return
    try:
        result_queue.put(("unexpected-acquire", ""))
    finally:
        checkpoint.release_writer_lease(lease)


def _authorization(
    binding: checkpoint.AttemptBinding, document: dict
) -> tuple[checkpoint.CheckpointHeadExpectation, _SyntheticHeadAnchorAuthority]:
    expectation = checkpoint.CheckpointHeadExpectation(
        attempt_id=document["attempt_id"],
        binding=binding,
        ledger_sha256=document["ledger_sha256"],
        anchor_id=f"synthetic://checkpoint/{document['attempt_id']}",
        anchor_sha256="d" * 64,
    )
    return expectation, _SyntheticHeadAnchorAuthority(expectation)


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
            created_expectation, created_authority = _authorization(binding, created)
            with checkpoint.writer_lease(
                path,
                expectation=created_expectation,
                anchor_authority=created_authority,
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
            resumed_expectation, resumed_authority = _authorization(binding, second)
            resumed = checkpoint.resume_attempt(
                path, expectation=resumed_expectation, anchor_authority=resumed_authority
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
            _, created_authority = _authorization(binding, created)
            mismatches = (
                _binding(freeze="d"),
                _binding(source="d"),
                _binding(code="d"),
            )
            for mismatch in mismatches:
                with self.subTest(mismatch=mismatch):
                    mismatch_expectation, _ = _authorization(mismatch, created)
                    with self.assertRaises(checkpoint.CheckpointLedgerError):
                        checkpoint.resume_attempt(
                            path,
                            expectation=mismatch_expectation,
                            anchor_authority=created_authority,
                        )
            created_expectation, _ = _authorization(binding, created)
            self.assertEqual(
                checkpoint.resume_attempt(
                    path,
                    expectation=created_expectation,
                    anchor_authority=created_authority,
                )["attempt_id"],
                "synthetic-v2.7-attempt-001",
            )

    def test_single_attempt_and_terminal_state_reject_resume_and_updates(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            created_expectation, created_authority = _authorization(binding, created)
            with self.assertRaises(checkpoint.CheckpointLedgerError):
                checkpoint.create_attempt(path, attempt_id="second-attempt", binding=binding)
            with checkpoint.writer_lease(
                path,
                expectation=created_expectation,
                anchor_authority=created_authority,
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
                terminal_expectation, terminal_authority = _authorization(binding, terminal)
                checkpoint.resume_attempt(
                    path,
                    expectation=terminal_expectation,
                    anchor_authority=terminal_authority,
                )

    def test_tamper_is_rejected_before_resume(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            created_expectation, created_authority = _authorization(binding, created)
            document = json.loads(path.read_text(encoding="utf-8"))
            document["entries"][0]["payload"]["metadata"]["scope"] = "tampered"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(checkpoint.CheckpointLedgerError):
                checkpoint.resume_attempt(
                    path,
                    expectation=created_expectation,
                    anchor_authority=created_authority,
                )

    def test_resume_rejects_a_restored_old_head_when_anchor_expects_terminal_head(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            old_active_bytes = path.read_bytes()
            created_expectation, created_authority = _authorization(binding, created)
            with checkpoint.writer_lease(
                path,
                expectation=created_expectation,
                anchor_authority=created_authority,
                writer_id="synthetic-rollback-writer",
            ) as lease:
                terminal = checkpoint.finalize_attempt(
                    path,
                    binding=binding,
                    terminal_state="completed",
                    recorded_at_utc="2026-08-05T00:01:00Z",
                    expected_ledger_sha256=created["ledger_sha256"],
                    lease=lease,
                )
            terminal_expectation, terminal_authority = _authorization(binding, terminal)
            path.write_bytes(old_active_bytes)
            with self.assertRaisesRegex(checkpoint.CheckpointLedgerError, "expected head"):
                checkpoint.resume_attempt(
                    path,
                    expectation=terminal_expectation,
                    anchor_authority=terminal_authority,
                )

    def test_resume_requires_an_injected_head_authority(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            expectation, _ = _authorization(binding, created)
            with self.assertRaisesRegex(checkpoint.CheckpointLedgerError, "HeadAnchorAuthority"):
                checkpoint.resume_attempt(
                    path,
                    expectation=expectation,
                    anchor_authority=object(),
                )

    def test_writer_lease_blocks_a_second_writer_and_pins_the_head(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            created_expectation, created_authority = _authorization(binding, created)
            with checkpoint.writer_lease(
                path,
                expectation=created_expectation,
                anchor_authority=created_authority,
                writer_id="synthetic-runner-a",
                acquired_at_utc="2026-08-05T00:00:30Z",
            ) as lease:
                with self.assertRaisesRegex(checkpoint.CheckpointLedgerError, "checkpoint gate"):
                    checkpoint.acquire_writer_lease(
                        path,
                        expectation=created_expectation,
                        anchor_authority=created_authority,
                        writer_id="synthetic-runner-b",
                    )
                with self.assertRaisesRegex(checkpoint.CheckpointLedgerError, "checkpoint gate"):
                    checkpoint.resume_attempt(
                        path,
                        expectation=created_expectation,
                        anchor_authority=created_authority,
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
            first_expectation, first_authority = _authorization(binding, first)
            self.assertEqual(
                checkpoint.resume_attempt(
                    path,
                    expectation=first_expectation,
                    anchor_authority=first_authority,
                )["ledger_sha256"],
                first["ledger_sha256"],
            )

    def test_sidecar_fields_cannot_reconstruct_a_writer_capability(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            expectation, authority = _authorization(binding, created)
            with checkpoint.writer_lease(
                path,
                expectation=expectation,
                anchor_authority=authority,
                writer_id="synthetic-genuine-writer",
            ) as lease:
                sidecar = json.loads(lease.lock_path.read_text(encoding="utf-8"))
                forged = checkpoint.WriterLease(
                    ledger_path=lease.ledger_path,
                    lock_path=lease.lock_path,
                    attempt_id=sidecar["attempt_id"],
                    writer_id=sidecar["writer_id"],
                    token=sidecar["token"],
                    _gate=lease._gate,
                    _capability=object(),
                    _sidecar_identity=lease._sidecar_identity,
                    _owner_pid=lease._owner_pid,
                    _write_mutex=threading.RLock(),
                )
                with self.assertRaisesRegex(checkpoint.CheckpointLedgerError, "not issued"):
                    checkpoint.append_checkpoint(
                        path,
                        binding=binding,
                        checkpoint_id="forged-grid-00",
                        expected_ledger_sha256=created["ledger_sha256"],
                        lease=forged,
                    )
                self.assertEqual(checkpoint.verify_ledger(path)["ledger_sha256"], created["ledger_sha256"])

    def test_cross_process_gate_rejects_a_second_writer(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            expectation, authority = _authorization(binding, created)
            with checkpoint.writer_lease(
                path,
                expectation=expectation,
                anchor_authority=authority,
                writer_id="synthetic-parent-writer",
            ):
                context = multiprocessing.get_context("spawn")
                result_queue = context.Queue()
                process = context.Process(
                    target=_attempt_competing_writer,
                    args=(str(path), expectation, result_queue),
                )
                process.start()
                process.join(timeout=15)
                self.assertFalse(process.is_alive(), "competing writer process did not exit")
                self.assertEqual(process.exitcode, 0)
                status, detail = result_queue.get(timeout=5)
                self.assertEqual(status, "blocked")
                self.assertIn("checkpoint gate", detail)
                process.close()

    def test_shared_lease_updates_are_serialized_by_the_live_mutex(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            expectation, authority = _authorization(binding, created)
            outcomes: list[tuple[str, str]] = []
            outcomes_lock = threading.Lock()
            start = threading.Barrier(3)
            with checkpoint.writer_lease(
                path,
                expectation=expectation,
                anchor_authority=authority,
                writer_id="synthetic-threaded-writer",
            ) as lease:
                def append_from_thread(checkpoint_id: str) -> None:
                    start.wait()
                    try:
                        checkpoint.append_checkpoint(
                            path,
                            binding=binding,
                            checkpoint_id=checkpoint_id,
                            expected_ledger_sha256=created["ledger_sha256"],
                            lease=lease,
                        )
                    except checkpoint.CheckpointLedgerError as error:
                        outcome = ("blocked", str(error))
                    else:
                        outcome = ("updated", checkpoint_id)
                    with outcomes_lock:
                        outcomes.append(outcome)

                threads = [
                    threading.Thread(target=append_from_thread, args=(f"thread-grid-{index}",))
                    for index in range(2)
                ]
                for thread in threads:
                    thread.start()
                start.wait()
                for thread in threads:
                    thread.join(timeout=10)
                    self.assertFalse(thread.is_alive(), "checkpoint thread did not exit")
            self.assertEqual(sorted(status for status, _ in outcomes), ["blocked", "updated"])
            self.assertTrue(any("expected head" in detail for status, detail in outcomes if status == "blocked"))
            verified = checkpoint.verify_ledger(path)
            self.assertEqual(len(verified["entries"]), 2)

    def test_release_waits_for_an_inflight_append_before_dropping_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            expectation, authority = _authorization(binding, created)
            lease = checkpoint.acquire_writer_lease(
                path,
                expectation=expectation,
                anchor_authority=authority,
                writer_id="synthetic-release-race-writer",
            )
            append_entered = threading.Event()
            permit_replace = threading.Event()
            release_started = threading.Event()
            release_finished = threading.Event()
            append_errors: list[BaseException] = []
            release_errors: list[BaseException] = []
            original_replace = checkpoint._atomic_replace_json

            def blocking_replace(destination: Path, document: dict) -> None:
                append_entered.set()
                if not permit_replace.wait(timeout=10):
                    raise RuntimeError("test did not permit checkpoint replacement")
                original_replace(destination, document)

            def append_worker() -> None:
                try:
                    checkpoint.append_checkpoint(
                        path,
                        binding=binding,
                        checkpoint_id="release-race-grid-00",
                        expected_ledger_sha256=created["ledger_sha256"],
                        lease=lease,
                    )
                except BaseException as error:
                    append_errors.append(error)

            def release_worker() -> None:
                release_started.set()
                try:
                    checkpoint.release_writer_lease(lease)
                except BaseException as error:
                    release_errors.append(error)
                finally:
                    release_finished.set()

            append_thread = threading.Thread(target=append_worker)
            release_thread = threading.Thread(target=release_worker)
            try:
                with patch.object(checkpoint, "_atomic_replace_json", side_effect=blocking_replace):
                    append_thread.start()
                    self.assertTrue(append_entered.wait(timeout=10))
                    release_thread.start()
                    self.assertTrue(release_started.wait(timeout=10))
                    self.assertFalse(release_finished.wait(timeout=0.2))
                    self.assertTrue(lease.lock_path.exists())
                    with self.assertRaisesRegex(checkpoint.CheckpointLedgerError, "checkpoint gate"):
                        checkpoint.acquire_writer_lease(
                            path,
                            expectation=expectation,
                            anchor_authority=authority,
                            writer_id="synthetic-release-race-rival",
                        )
                    permit_replace.set()
                    append_thread.join(timeout=10)
                    release_thread.join(timeout=10)
                self.assertFalse(append_thread.is_alive())
                self.assertFalse(release_thread.is_alive())
                self.assertEqual(append_errors, [])
                self.assertEqual(release_errors, [])
                self.assertTrue(release_finished.is_set())
                self.assertFalse(lease.lock_path.exists())
            finally:
                permit_replace.set()
                append_thread.join(timeout=10)
                release_thread.join(timeout=10)
                if (lease.ledger_path, lease.token) in checkpoint._ISSUED_LEASE_CAPABILITIES:
                    checkpoint.release_writer_lease(lease)

    def test_timestamp_validation_rejects_invalid_and_nonmonotonic_updates(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path, binding, created = self._create(Path(raw_directory))
            created_expectation, created_authority = _authorization(binding, created)
            with self.assertRaisesRegex(checkpoint.CheckpointLedgerError, "ISO-8601 UTC"):
                checkpoint.create_attempt(
                    Path(raw_directory) / "bad-time.json",
                    attempt_id="synthetic-bad-time",
                    binding=binding,
                    started_at_utc="2026-08-05T00:00:00+00:00",
                )
            with checkpoint.writer_lease(
                path,
                expectation=created_expectation,
                anchor_authority=created_authority,
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
            created_expectation, created_authority = _authorization(binding, created)
            before = path.read_bytes()
            with checkpoint.writer_lease(
                path,
                expectation=created_expectation,
                anchor_authority=created_authority,
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
            created_expectation, created_authority = _authorization(binding, created)
            self.assertEqual(
                checkpoint.resume_attempt(
                    path,
                    expectation=created_expectation,
                    anchor_authority=created_authority,
                )["state"],
                checkpoint.ACTIVE_STATE,
            )


if __name__ == "__main__":
    unittest.main()
