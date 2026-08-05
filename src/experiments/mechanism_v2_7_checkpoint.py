"""Append-only, synthetic-only checkpoint ledger for mechanism-v2.7.

This module deliberately knows nothing about MORPHO, HDF5, waveforms, or
experiment protocols.  Its only persistent state is a small JSON ledger whose
caller-supplied binding pins one *attempt* to a frozen protocol receipt, a
source receipt, and a code receipt.  It is therefore safe to test before any
new waveform-access workflow exists.

The ledger provides:

* exclusive creation of one attempt per ledger path;
* an explicit, fail-closed writer lease held across a runner lifetime;
* atomic replacement for every post-creation update;
* a SHA-256 chain over every entry plus a document seal;
* resume/update only at a caller-pinned ledger head with strictly increasing UTC timestamps;
* resume only when the freeze, source, and code hashes are identical; and
* terminal states which permanently reject resume and further updates.

SHA-256 supplies tamper evidence, not a secret signature.  A party able to
rewrite the complete ledger and recompute every public hash is outside this
local checkpoint guard; an externally stored freeze receipt remains the
authority for that stronger threat model.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Protocol


LEDGER_FORMAT = "mechanism-v2.7-checkpoint-ledger-v1"
WRITER_LOCK_FORMAT = "mechanism-v2.7-writer-lease-v1"
GATE_FORMAT = "mechanism-v2.7-checkpoint-gate-v1"
ACTIVE_STATE = "active"
TERMINAL_STATES = frozenset({"completed", "invalidated", "aborted"})
GENESIS_PREVIOUS_SHA256 = "0" * 64
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_UTC_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")
_BINDING_FIELDS = ("freeze_sha256", "source_sha256", "code_sha256")
_DOCUMENT_FIELDS = frozenset(
    {
        "format",
        "attempt_id",
        "binding",
        "binding_sha256",
        "metadata",
        "state",
        "entries",
        "ledger_sha256",
    }
)


class CheckpointLedgerError(RuntimeError):
    """Raised when an attempt ledger is unsafe to create, resume, or update."""


class HeadAnchorAuthority(Protocol):
    """External, immutable-head verifier required for resume and final audit.

    The local ledger cannot prove that a hash-valid old file was not restored.
    A future frozen runner must therefore inject a verifier for an append-only,
    independently retained head anchor.  This module deliberately ships no
    production implementation: a plain local JSON file or mutable Git branch
    is not sufficient authority for a real confirmation run.
    """

    def verify_head(self, expectation: "CheckpointHeadExpectation") -> bool:
        """Return ``True`` only when the independently retained anchor matches."""


@dataclass(frozen=True)
class AttemptBinding:
    """Immutable public identities that must all match before a resume.

    Values are intentionally supplied by the caller.  This checkpoint layer
    must not discover, open, or hash a real source file itself.
    """

    freeze_sha256: str
    source_sha256: str
    code_sha256: str

    def __post_init__(self) -> None:
        for field_name in _BINDING_FIELDS:
            _require_digest(field_name, getattr(self, field_name))

    def as_dict(self) -> dict[str, str]:
        return {field_name: getattr(self, field_name) for field_name in _BINDING_FIELDS}


@dataclass(frozen=True)
class CheckpointHeadExpectation:
    """A head identity which must be verified outside the mutable worktree.

    ``anchor_id`` is deliberately opaque.  A source-specific frozen runner
    must define how it resolves to an append-only, independently retained
    record; this synthetic layer only requires a verifier to attest it.
    """

    attempt_id: str
    binding: AttemptBinding
    ledger_sha256: str
    anchor_id: str
    anchor_sha256: str

    def __post_init__(self) -> None:
        _require(isinstance(self.attempt_id, str) and self.attempt_id, "attempt_id must be a non-empty string")
        if not isinstance(self.binding, AttemptBinding):
            raise CheckpointLedgerError("head expectation binding must be an AttemptBinding")
        _require_digest("head expectation ledger_sha256", self.ledger_sha256)
        _require(isinstance(self.anchor_id, str) and self.anchor_id, "anchor_id must be a non-empty string")
        _require_digest("head expectation anchor_sha256", self.anchor_sha256)


@dataclass(frozen=True)
class WriterLease:
    """Exclusive writer identity for one active synthetic attempt ledger.

    The lease is intentionally process-local and backed by a sidecar file.
    A real runner must hold it for its full one-shot or resume lifetime, not
    merely while serializing a checkpoint.  A stale lease is never removed
    automatically because doing so could permit a second writer after an
    unobserved process split.
    """

    ledger_path: Path
    lock_path: Path
    attempt_id: str
    writer_id: str
    token: str
    _gate: "_GateHandle" = field(repr=False, compare=False)
    _capability: object = field(repr=False, compare=False)
    _sidecar_identity: tuple[int, int] = field(repr=False, compare=False)
    _owner_pid: int = field(repr=False, compare=False)
    _write_mutex: Any = field(repr=False, compare=False)


# This process-local registry makes a deserialized or manually reconstructed
# WriterLease fail even if its caller copied every public sidecar field.  The
# OS gate below supplies the corresponding cross-process capability.
_ISSUED_LEASE_CAPABILITIES: dict[tuple[Path, str], object] = {}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckpointLedgerError(message)


def _require_digest(name: str, value: Any) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise CheckpointLedgerError(f"{name} must be a lowercase 64-character SHA-256 hex digest")
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CheckpointLedgerError(f"ledger content must be canonical JSON: {error}") from error


def _canonical_json_value(value: Any) -> Any:
    """Deep-copy a JSON-compatible value while rejecting NaN and custom types."""

    return json.loads(_canonical_json_bytes(value).decode("utf-8"))


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _without_field(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    return {key: copy.deepcopy(item) for key, item in value.items() if key != field_name}


def _coerce_binding(binding: AttemptBinding | Mapping[str, str]) -> AttemptBinding:
    if isinstance(binding, AttemptBinding):
        return binding
    if not isinstance(binding, Mapping) or set(binding) != set(_BINDING_FIELDS):
        raise CheckpointLedgerError(f"binding must contain exactly {', '.join(_BINDING_FIELDS)}")
    return AttemptBinding(**{field_name: binding[field_name] for field_name in _BINDING_FIELDS})


def _parse_utc_timestamp(value: Any, field_name: str = "recorded_at_utc") -> datetime:
    """Accept only explicit ISO-8601 UTC timestamps used in a ledger.

    Offsets, naive timestamps, and non-parseable strings would make a ledger
    hash-valid but temporally ambiguous.  The public wire format is therefore
    deliberately restricted to a trailing ``Z`` UTC representation.
    """

    if not isinstance(value, str) or _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        raise CheckpointLedgerError(
            f"{field_name} must be an ISO-8601 UTC timestamp ending in Z"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CheckpointLedgerError(f"{field_name} is not a valid UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise CheckpointLedgerError(f"{field_name} must be UTC")
    return parsed


def _timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    _parse_utc_timestamp(value)
    return value


def _new_entry(
    *,
    sequence: int,
    event: str,
    attempt_id: str,
    binding_sha256: str,
    previous_entry_sha256: str,
    payload: Mapping[str, Any] | None,
    recorded_at_utc: str | None,
    checkpoint_id: str | None = None,
    terminal_state: str | None = None,
) -> dict[str, Any]:
    _require(sequence >= 0, "entry sequence must be non-negative")
    _require_digest("previous_entry_sha256", previous_entry_sha256)
    _require_digest("binding_sha256", binding_sha256)
    _require(isinstance(attempt_id, str) and attempt_id, "attempt_id must be a non-empty string")
    _require(event in {"attempt_started", "checkpoint", "terminal"}, "unknown ledger event")

    normalized_payload = _canonical_json_value(dict(payload or {}))
    entry: dict[str, Any] = {
        "sequence": sequence,
        "event": event,
        "attempt_id": attempt_id,
        "recorded_at_utc": _timestamp(recorded_at_utc),
        "previous_entry_sha256": previous_entry_sha256,
        "binding_sha256": binding_sha256,
        "payload": normalized_payload,
    }
    if event == "checkpoint":
        _require(isinstance(checkpoint_id, str) and checkpoint_id, "checkpoint_id must be a non-empty string")
        entry["checkpoint_id"] = checkpoint_id
    else:
        _require(checkpoint_id is None, "only checkpoint entries may have checkpoint_id")
    if event == "terminal":
        _require(terminal_state in TERMINAL_STATES, "terminal_state is not permitted")
        entry["terminal_state"] = terminal_state
    else:
        _require(terminal_state is None, "only terminal entries may have terminal_state")
    entry["entry_sha256"] = _json_sha256(entry)
    return entry


def _seal_document(document: Mapping[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(dict(document))
    sealed.pop("ledger_sha256", None)
    sealed["ledger_sha256"] = _json_sha256(sealed)
    return sealed


def _fsync_parent_best_effort(path: Path) -> None:
    """Flush directory metadata where the host permits directory handles."""

    try:
        descriptor = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _file_identity_from_stat(stat_result: os.stat_result) -> tuple[int, int]:
    return stat_result.st_dev, stat_result.st_ino


def _file_identity(path: Path) -> tuple[int, int]:
    try:
        return _file_identity_from_stat(path.stat())
    except OSError as error:
        raise CheckpointLedgerError(f"cannot stat checkpoint artifact: {path}") from error


def _gate_path(destination: Path) -> Path:
    return destination.with_name(f".{destination.name}.gate")


def _lock_gate_fd(fd: int, *, shared: bool) -> None:
    """Acquire a non-blocking OS lock on byte zero of a persistent gate."""

    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            mode = msvcrt.LK_NBRLCK if shared else msvcrt.LK_NBLCK
            msvcrt.locking(fd, mode, 1)
        else:
            import fcntl

            mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
            fcntl.flock(fd, mode | fcntl.LOCK_NB)
    except (ImportError, OSError) as error:
        raise CheckpointLedgerError("checkpoint gate is unavailable or already held") from error


def _unlock_gate_fd(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    except (ImportError, OSError):
        # Closing the descriptor below is still required.  A failed unlock
        # must never cause the caller to continue using the capability.
        pass


@dataclass
class _GateHandle:
    """A live OS-level gate capability; it is never reconstructed from JSON."""

    path: Path
    fd: int
    shared: bool
    identity: tuple[int, int]
    owner_pid: int
    _released: bool = False

    def assert_held(self, *, require_exclusive: bool = False) -> None:
        if self._released or self.fd < 0:
            raise CheckpointLedgerError("checkpoint gate capability has already been released")
        if self.owner_pid != os.getpid():
            raise CheckpointLedgerError("checkpoint gate capability belongs to another process")
        if require_exclusive and self.shared:
            raise CheckpointLedgerError("writer requires an exclusive checkpoint gate")
        try:
            descriptor_identity = _file_identity_from_stat(os.fstat(self.fd))
        except OSError as error:
            raise CheckpointLedgerError("checkpoint gate descriptor is no longer valid") from error
        if descriptor_identity != self.identity or _file_identity(self.path) != self.identity:
            raise CheckpointLedgerError("checkpoint gate identity changed; refusing to continue")

    def release(self) -> None:
        if self._released:
            return
        try:
            _unlock_gate_fd(self.fd)
        finally:
            try:
                os.close(self.fd)
            finally:
                self.fd = -1
                self._released = True


def _read_fd_bytes(fd: int) -> bytes:
    try:
        size = os.fstat(fd).st_size
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            block = os.read(fd, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
    except OSError as error:
        raise CheckpointLedgerError("cannot read checkpoint gate") from error
    payload = b"".join(chunks)
    if len(payload) != size:
        raise CheckpointLedgerError("checkpoint gate changed while it was being read")
    return payload


def _gate_document(document: Mapping[str, Any]) -> dict[str, str]:
    return {
        "format": GATE_FORMAT,
        "attempt_id": document["attempt_id"],
        "binding_sha256": document["binding_sha256"],
        "initial_ledger_sha256": document["ledger_sha256"],
    }


def _validate_gate_document(gate: _GateHandle, document: Mapping[str, Any]) -> None:
    gate.assert_held()
    try:
        payload = json.loads(_read_fd_bytes(gate.fd).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CheckpointLedgerError("checkpoint gate is not valid UTF-8 JSON") from error
    required_fields = {"format", "attempt_id", "binding_sha256", "initial_ledger_sha256"}
    if not isinstance(payload, dict) or set(payload) != required_fields:
        raise CheckpointLedgerError("checkpoint gate has an invalid field set")
    if payload.get("format") != GATE_FORMAT:
        raise CheckpointLedgerError("checkpoint gate format is not recognized")
    if payload.get("attempt_id") != document.get("attempt_id"):
        raise CheckpointLedgerError("checkpoint gate belongs to a different attempt")
    if payload.get("binding_sha256") != document.get("binding_sha256"):
        raise CheckpointLedgerError("checkpoint gate belongs to a different freeze/source/code binding")
    _require_digest("checkpoint gate initial_ledger_sha256", payload.get("initial_ledger_sha256"))


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(fd, payload[offset:])
        except OSError as error:
            raise CheckpointLedgerError("cannot write checkpoint gate") from error
        if written <= 0:
            raise CheckpointLedgerError("cannot write checkpoint gate")
        offset += written


def _create_gate(destination: Path, document: Mapping[str, Any]) -> _GateHandle:
    """Create the permanent gate once, then hold its exclusive OS lock."""

    path = _gate_path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(str(path), flags)
    except FileExistsError as error:
        raise CheckpointLedgerError(
            f"checkpoint gate already exists: {path}; never reuse or replace a prior attempt"
        ) from error
    try:
        os.set_inheritable(fd, False)
        _write_all(fd, _canonical_json_bytes(_gate_document(document)))
        os.fsync(fd)
        identity = _file_identity_from_stat(os.fstat(fd))
        _lock_gate_fd(fd, shared=False)
        handle = _GateHandle(path, fd, False, identity, os.getpid())
        handle.assert_held(require_exclusive=True)
        _fsync_parent_best_effort(path)
        return handle
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        # Do not remove a partially created gate.  A residual gate is
        # intentional fail-closed evidence, not a retriable namespace.
        raise


def _open_gate(destination: Path, *, shared: bool) -> _GateHandle:
    path = _gate_path(destination)
    # A final auditor never writes the persistent gate.  On Windows this also
    # proves that the shared msvcrt read lock works for a genuinely read-only
    # independent process rather than relying on worktree write permission.
    flags = (os.O_RDONLY if shared else os.O_RDWR) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(str(path), flags)
    except FileNotFoundError as error:
        raise CheckpointLedgerError("checkpoint gate is missing; refusing an unguarded operation") from error
    except OSError as error:
        raise CheckpointLedgerError("cannot open checkpoint gate") from error
    try:
        os.set_inheritable(fd, False)
        identity = _file_identity_from_stat(os.fstat(fd))
        _lock_gate_fd(fd, shared=shared)
        handle = _GateHandle(path, fd, shared, identity, os.getpid())
        handle.assert_held(require_exclusive=not shared)
        return handle
    except BaseException:
        try:
            os.close(fd)
        finally:
            raise


@contextmanager
def checkpoint_audit_guard(ledger_path: str | Path) -> Iterator[_GateHandle]:
    """Hold the shared OS gate used by the independent read-only auditor."""

    destination = Path(ledger_path)
    try:
        resolved_destination = destination.resolve(strict=True)
    except OSError as error:
        raise CheckpointLedgerError(f"cannot resolve ledger for audit guard: {destination}") from error
    gate = _open_gate(resolved_destination, shared=True)
    try:
        yield gate
    finally:
        gate.release()


def _write_temp_bytes(destination: Path, payload: bytes) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise
    return temporary


def _atomic_create_json(destination: Path, document: Mapping[str, Any]) -> None:
    """Create a ledger exactly once without replacing a competing attempt."""

    temporary = _write_temp_bytes(destination, _canonical_json_bytes(document))
    try:
        try:
            # A hard link is an atomic no-overwrite publication on the same
            # filesystem, unlike os.replace which would overwrite a rival.
            os.link(temporary, destination)
        except FileExistsError as error:
            raise CheckpointLedgerError(f"attempt ledger already exists: {destination}") from error
        except OSError as error:
            # Some local filesystems do not support hard links.  The fallback
            # preserves exclusive creation, while normal updates still use
            # replacement of fully flushed temporary files.
            if error.errno not in {errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP}:
                raise
            try:
                descriptor = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            except FileExistsError as create_error:
                raise CheckpointLedgerError(f"attempt ledger already exists: {destination}") from create_error
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(temporary.read_bytes())
                    handle.flush()
                    os.fsync(handle.fileno())
            except BaseException:
                try:
                    destination.unlink(missing_ok=True)
                finally:
                    raise
        _fsync_parent_best_effort(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_replace_json(destination: Path, document: Mapping[str, Any]) -> None:
    """Publish a fully flushed replacement, leaving the old ledger on failure."""

    _require(destination.exists(), f"attempt ledger does not exist: {destination}")
    temporary = _write_temp_bytes(destination, _canonical_json_bytes(document))
    try:
        os.replace(temporary, destination)
        _fsync_parent_best_effort(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _writer_lock_path(destination: Path) -> Path:
    return destination.with_name(f".{destination.name}.writer.lock")


def _read_writer_lock(lock_path: Path) -> dict[str, Any]:
    try:
        raw = lock_path.read_bytes()
    except FileNotFoundError as error:
        raise CheckpointLedgerError(f"writer lease does not exist: {lock_path}") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CheckpointLedgerError(
            "writer lease exists but cannot be audited; manual recovery is required"
        ) from error
    if not isinstance(value, dict):
        raise CheckpointLedgerError("writer lease exists but is not an object; manual recovery is required")
    return value


def _validate_writer_lock(document: Mapping[str, Any]) -> dict[str, Any]:
    required_fields = {
        "format",
        "attempt_id",
        "writer_id",
        "token",
        "pid",
        "acquired_at_utc",
        "ledger_sha256",
    }
    if set(document) != required_fields:
        raise CheckpointLedgerError("writer lease exists but has an invalid field set; manual recovery is required")
    if document.get("format") != WRITER_LOCK_FORMAT:
        raise CheckpointLedgerError("writer lease format is not recognized; manual recovery is required")
    for field_name in ("attempt_id", "writer_id", "token"):
        if not isinstance(document.get(field_name), str) or not document[field_name]:
            raise CheckpointLedgerError(f"writer lease has an invalid {field_name}; manual recovery is required")
    if not isinstance(document.get("pid"), int) or isinstance(document["pid"], bool) or document["pid"] <= 0:
        raise CheckpointLedgerError("writer lease has an invalid pid; manual recovery is required")
    _parse_utc_timestamp(document.get("acquired_at_utc"), "writer lease acquired_at_utc")
    _require_digest("writer lease ledger_sha256", document.get("ledger_sha256"))
    return copy.deepcopy(dict(document))


def _write_exclusive_writer_lock(lock_path: Path, document: Mapping[str, Any]) -> tuple[int, int]:
    payload = _canonical_json_bytes(document)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as error:
        try:
            existing = _validate_writer_lock(_read_writer_lock(lock_path))
            detail = (
                f"attempt={existing['attempt_id']} writer={existing['writer_id']} "
                f"pid={existing['pid']} acquired_at_utc={existing['acquired_at_utc']}"
            )
        except CheckpointLedgerError as lock_error:
            detail = str(lock_error)
        raise CheckpointLedgerError(
            f"writer lease already exists for this attempt ({detail}); it is never removed automatically"
        ) from error
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_parent_best_effort(lock_path)
        return _file_identity(lock_path)
    except BaseException:
        try:
            lock_path.unlink(missing_ok=True)
        finally:
            raise


def _assert_no_writer_lock(destination: Path) -> None:
    lock_path = _writer_lock_path(destination)
    if not lock_path.exists():
        return
    try:
        existing = _validate_writer_lock(_read_writer_lock(lock_path))
        detail = (
            f"attempt={existing['attempt_id']} writer={existing['writer_id']} "
            f"pid={existing['pid']} acquired_at_utc={existing['acquired_at_utc']}"
        )
    except CheckpointLedgerError as error:
        detail = str(error)
    raise CheckpointLedgerError(
        f"writer lease exists ({detail}); audit it and prove the writer is dead before manual recovery"
    )


def _require_owned_writer_lease(
    lease: WriterLease | None,
    *,
    destination: Path,
    document: Mapping[str, Any],
) -> WriterLease:
    if not isinstance(lease, WriterLease):
        raise CheckpointLedgerError("an exclusive WriterLease is required for every ledger update")
    if lease._owner_pid != os.getpid():
        raise CheckpointLedgerError("writer lease belongs to another process")
    try:
        resolved_destination = destination.resolve(strict=True)
    except OSError as error:
        raise CheckpointLedgerError(f"cannot resolve ledger for writer lease: {destination}") from error
    if lease.ledger_path != resolved_destination or lease.lock_path != _writer_lock_path(resolved_destination):
        raise CheckpointLedgerError("writer lease belongs to a different ledger")
    issued_capability = _ISSUED_LEASE_CAPABILITIES.get((lease.ledger_path, lease.token))
    if issued_capability is not lease._capability:
        raise CheckpointLedgerError("writer lease was not issued by this live process")
    lease._gate.assert_held(require_exclusive=True)
    if lease._gate.path != _gate_path(resolved_destination):
        raise CheckpointLedgerError("writer lease is bound to a different checkpoint gate")
    if _file_identity(lease.lock_path) != lease._sidecar_identity:
        raise CheckpointLedgerError("writer lease sidecar identity changed; refusing to continue")
    lock = _validate_writer_lock(_read_writer_lock(lease.lock_path))
    if (
        lock["token"] != lease.token
        or lock["writer_id"] != lease.writer_id
        or lock["attempt_id"] != lease.attempt_id
        or lock["attempt_id"] != document["attempt_id"]
    ):
        raise CheckpointLedgerError("writer lease ownership does not match the active attempt")
    return lease


def _read_json(ledger_path: Path) -> dict[str, Any]:
    try:
        raw = ledger_path.read_bytes()
    except FileNotFoundError as error:
        raise CheckpointLedgerError(f"attempt ledger does not exist: {ledger_path}") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CheckpointLedgerError(f"attempt ledger is not valid UTF-8 JSON: {ledger_path}") from error
    if not isinstance(value, dict):
        raise CheckpointLedgerError("attempt ledger root must be an object")
    return value


def _validate_entry(
    entry: Any,
    *,
    expected_sequence: int,
    expected_previous_sha256: str,
    expected_attempt_id: str,
    expected_binding_sha256: str,
    is_first: bool,
) -> tuple[str, str | None, datetime]:
    if not isinstance(entry, dict):
        raise CheckpointLedgerError(f"ledger entry {expected_sequence} must be an object")
    event = entry.get("event")
    allowed_fields = {
        "sequence",
        "event",
        "attempt_id",
        "recorded_at_utc",
        "previous_entry_sha256",
        "binding_sha256",
        "payload",
        "entry_sha256",
    }
    if event == "checkpoint":
        allowed_fields.add("checkpoint_id")
    elif event == "terminal":
        allowed_fields.add("terminal_state")
    elif event != "attempt_started":
        raise CheckpointLedgerError(f"ledger entry {expected_sequence} has an unknown event")
    if set(entry) != allowed_fields:
        raise CheckpointLedgerError(f"ledger entry {expected_sequence} has an invalid field set")
    if not isinstance(entry.get("sequence"), int) or isinstance(entry["sequence"], bool) or entry["sequence"] != expected_sequence:
        raise CheckpointLedgerError(f"ledger entry {expected_sequence} has an invalid sequence")
    if entry["previous_entry_sha256"] != expected_previous_sha256:
        raise CheckpointLedgerError(f"ledger entry {expected_sequence} breaks the hash chain")
    _require_digest(f"entries[{expected_sequence}].previous_entry_sha256", entry["previous_entry_sha256"])
    if entry["attempt_id"] != expected_attempt_id:
        raise CheckpointLedgerError(f"ledger entry {expected_sequence} is bound to a different attempt")
    if entry["binding_sha256"] != expected_binding_sha256:
        raise CheckpointLedgerError(f"ledger entry {expected_sequence} is bound to a different freeze/source/code identity")
    _require_digest(f"entries[{expected_sequence}].binding_sha256", entry["binding_sha256"])
    recorded_at = _parse_utc_timestamp(
        entry.get("recorded_at_utc"), f"ledger entry {expected_sequence} recorded_at_utc"
    )
    if not isinstance(entry.get("payload"), dict):
        raise CheckpointLedgerError(f"ledger entry {expected_sequence} payload must be an object")
    if is_first and event != "attempt_started":
        raise CheckpointLedgerError("first ledger entry must be attempt_started")
    if not is_first and event == "attempt_started":
        raise CheckpointLedgerError("attempt_started may appear only once")
    if event == "checkpoint" and (not isinstance(entry["checkpoint_id"], str) or not entry["checkpoint_id"]):
        raise CheckpointLedgerError(f"ledger entry {expected_sequence} has an invalid checkpoint_id")
    terminal_state = None
    if event == "terminal":
        terminal_state = entry["terminal_state"]
        if terminal_state not in TERMINAL_STATES:
            raise CheckpointLedgerError(f"ledger entry {expected_sequence} has an invalid terminal_state")
    _require_digest(f"entries[{expected_sequence}].entry_sha256", entry.get("entry_sha256"))
    if entry["entry_sha256"] != _json_sha256(_without_field(entry, "entry_sha256")):
        raise CheckpointLedgerError(f"ledger entry {expected_sequence} SHA-256 does not match its content")
    return entry["entry_sha256"], terminal_state, recorded_at


def _validate_document(document: Mapping[str, Any]) -> dict[str, Any]:
    if set(document) != _DOCUMENT_FIELDS:
        raise CheckpointLedgerError("attempt ledger has an invalid top-level field set")
    if document.get("format") != LEDGER_FORMAT:
        raise CheckpointLedgerError("attempt ledger format is not mechanism-v2.7-checkpoint-ledger-v1")
    attempt_id = document.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise CheckpointLedgerError("attempt ledger lacks a non-empty attempt_id")
    binding = _coerce_binding(document.get("binding"))
    binding_sha256 = _json_sha256(binding.as_dict())
    if document.get("binding_sha256") != binding_sha256:
        raise CheckpointLedgerError("attempt ledger binding SHA-256 does not match freeze/source/code hashes")
    _require_digest("binding_sha256", document["binding_sha256"])
    if not isinstance(document.get("metadata"), dict):
        raise CheckpointLedgerError("attempt ledger metadata must be an object")
    if not isinstance(document.get("entries"), list) or not document["entries"]:
        raise CheckpointLedgerError("attempt ledger must contain a start entry")
    _require_digest("ledger_sha256", document.get("ledger_sha256"))
    if document["ledger_sha256"] != _json_sha256(_without_field(document, "ledger_sha256")):
        raise CheckpointLedgerError("attempt ledger SHA-256 does not match its content")

    previous = GENESIS_PREVIOUS_SHA256
    previous_recorded_at: datetime | None = None
    checkpoint_ids: set[str] = set()
    terminal_states: list[str] = []
    for sequence, entry in enumerate(document["entries"]):
        entry_hash, terminal_state, recorded_at = _validate_entry(
            entry,
            expected_sequence=sequence,
            expected_previous_sha256=previous,
            expected_attempt_id=attempt_id,
            expected_binding_sha256=binding_sha256,
            is_first=(sequence == 0),
        )
        if previous_recorded_at is not None and recorded_at <= previous_recorded_at:
            raise CheckpointLedgerError("ledger timestamps must be strictly increasing UTC instants")
        if entry["event"] == "checkpoint":
            checkpoint_id = entry["checkpoint_id"]
            if checkpoint_id in checkpoint_ids:
                raise CheckpointLedgerError(f"checkpoint_id is repeated: {checkpoint_id}")
            checkpoint_ids.add(checkpoint_id)
        if terminal_state is not None:
            terminal_states.append(terminal_state)
            if sequence != len(document["entries"]) - 1:
                raise CheckpointLedgerError("terminal entry must be the final ledger entry")
        previous = entry_hash
        previous_recorded_at = recorded_at

    state = document.get("state")
    if state == ACTIVE_STATE:
        if terminal_states:
            raise CheckpointLedgerError("active ledger must not contain a terminal entry")
    elif state in TERMINAL_STATES:
        if terminal_states != [state]:
            raise CheckpointLedgerError("terminal ledger state must match its final terminal entry")
    else:
        raise CheckpointLedgerError("attempt ledger has an invalid state")
    return copy.deepcopy(dict(document))


def verify_ledger(ledger_path: str | Path) -> dict[str, Any]:
    """Read and validate a ledger without authorizing a resume."""

    return _validate_document(_read_json(Path(ledger_path)))


def acquire_writer_lease(
    ledger_path: str | Path,
    *,
    expectation: CheckpointHeadExpectation,
    anchor_authority: HeadAnchorAuthority,
    writer_id: str,
    acquired_at_utc: str | None = None,
) -> WriterLease:
    """Acquire the only writer lease for an active attempt at one known head.

    The caller must retain the returned lease for the full real runner lifetime
    and pass it to every checkpoint or terminal update.  Existing leases are
    fail-closed, including stale or malformed sidecars; a later recovery path
    must explicitly audit and prove a dead writer instead of silently deleting
    a lock.
    """

    _require(isinstance(writer_id, str) and writer_id, "writer_id must be a non-empty string")
    destination = Path(ledger_path)
    try:
        resolved_destination = destination.resolve(strict=True)
    except OSError as error:
        raise CheckpointLedgerError(f"cannot resolve ledger for writer lease: {destination}") from error
    gate = _open_gate(resolved_destination, shared=False)
    lease: WriterLease | None = None
    try:
        document = verify_ledger(resolved_destination)
        _validate_gate_document(gate, document)
        _assert_no_writer_lock(resolved_destination)
        _require_head_expectation(document, expectation)
        verify_head_anchor(anchor_authority, expectation)
        _require_active(document)
        lock_path = _writer_lock_path(resolved_destination)
        token = uuid.uuid4().hex
        lock_document = {
            "format": WRITER_LOCK_FORMAT,
            "attempt_id": document["attempt_id"],
            "writer_id": writer_id,
            "token": token,
            "pid": os.getpid(),
            "acquired_at_utc": _timestamp(acquired_at_utc),
            "ledger_sha256": document["ledger_sha256"],
        }
        _validate_writer_lock(lock_document)
        sidecar_identity = _write_exclusive_writer_lock(lock_path, lock_document)
        capability = object()
        lease = WriterLease(
            ledger_path=resolved_destination,
            lock_path=lock_path,
            attempt_id=document["attempt_id"],
            writer_id=writer_id,
            token=token,
            _gate=gate,
            _capability=capability,
            _sidecar_identity=sidecar_identity,
            _owner_pid=os.getpid(),
            _write_mutex=threading.RLock(),
        )
        _ISSUED_LEASE_CAPABILITIES[(lease.ledger_path, lease.token)] = capability
        current = verify_ledger(resolved_destination)
        _validate_gate_document(gate, current)
        _require_head_expectation(current, expectation)
        verify_head_anchor(anchor_authority, expectation)
        _require_active(current)
        _require_owned_writer_lease(lease, destination=resolved_destination, document=current)
    except BaseException:
        if lease is not None:
            release_writer_lease(lease)
        else:
            gate.release()
        raise
    return lease


def release_writer_lease(lease: WriterLease) -> None:
    """Release a live capability, retaining a sidecar if cleanup is uncertain."""

    if not isinstance(lease, WriterLease):
        raise CheckpointLedgerError("release requires a WriterLease")
    issued = _ISSUED_LEASE_CAPABILITIES.get((lease.ledger_path, lease.token)) is lease._capability
    if not issued:
        raise CheckpointLedgerError("writer lease was not issued by this live process")
    # This is the same mutex held across verify -> append -> replace.  Without
    # it, a sibling thread could delete the sidecar and release the OS gate
    # after an append has checked its head but before it publishes the update.
    with lease._write_mutex:
        issued = _ISSUED_LEASE_CAPABILITIES.get((lease.ledger_path, lease.token)) is lease._capability
        if not issued:
            raise CheckpointLedgerError("writer lease was already released by this process")
        try:
            document = verify_ledger(lease.ledger_path)
            _require_owned_writer_lease(lease, destination=lease.ledger_path, document=document)
            lock = _validate_writer_lock(_read_writer_lock(lease.lock_path))
            if (
                lock["token"] != lease.token
                or lock["writer_id"] != lease.writer_id
                or lock["attempt_id"] != lease.attempt_id
            ):
                raise CheckpointLedgerError("writer lease ownership changed; refusing to remove another writer's lock")
            lease.lock_path.unlink()
            _fsync_parent_best_effort(lease.lock_path)
        finally:
            # If the ownership checks or unlink fail, the sidecar remains as
            # explicit fail-closed recovery evidence.  The OS capability must
            # still be released so a crash does not leave an invisible lock.
            _ISSUED_LEASE_CAPABILITIES.pop((lease.ledger_path, lease.token), None)
            lease._gate.release()


@contextmanager
def writer_lease(
    ledger_path: str | Path,
    *,
    expectation: CheckpointHeadExpectation,
    anchor_authority: HeadAnchorAuthority,
    writer_id: str,
    acquired_at_utc: str | None = None,
) -> Iterator[WriterLease]:
    """Context manager that guarantees release after a synthetic writer exits."""

    lease = acquire_writer_lease(
        ledger_path,
        expectation=expectation,
        anchor_authority=anchor_authority,
        writer_id=writer_id,
        acquired_at_utc=acquired_at_utc,
    )
    try:
        yield lease
    finally:
        release_writer_lease(lease)


def _require_matching_binding(document: Mapping[str, Any], binding: AttemptBinding | Mapping[str, str]) -> AttemptBinding:
    requested = _coerce_binding(binding)
    stored = _coerce_binding(document["binding"])
    if requested != stored:
        raise CheckpointLedgerError("resume/update binding differs from the frozen freeze/source/code identity")
    return requested


def _require_active(document: Mapping[str, Any]) -> None:
    if document["state"] != ACTIVE_STATE:
        raise CheckpointLedgerError(f"attempt is terminal ({document['state']}) and cannot be resumed or updated")


def _require_expected_head(document: Mapping[str, Any], expected_ledger_sha256: str | None) -> None:
    if expected_ledger_sha256 is None:
        raise CheckpointLedgerError("expected_ledger_sha256 is required for resume and every ledger update")
    _require_digest("expected_ledger_sha256", expected_ledger_sha256)
    if document["ledger_sha256"] != expected_ledger_sha256:
        raise CheckpointLedgerError("ledger changed since the caller's expected head")


def _require_head_expectation(
    document: Mapping[str, Any], expectation: CheckpointHeadExpectation
) -> CheckpointHeadExpectation:
    if not isinstance(expectation, CheckpointHeadExpectation):
        raise CheckpointLedgerError("a CheckpointHeadExpectation is required")
    if document.get("attempt_id") != expectation.attempt_id:
        raise CheckpointLedgerError("ledger attempt_id differs from the externally expected head")
    _require_matching_binding(document, expectation.binding)
    _require_expected_head(document, expectation.ledger_sha256)
    return expectation


def verify_head_anchor(
    authority: HeadAnchorAuthority | Any, expectation: CheckpointHeadExpectation
) -> None:
    """Require an injected verifier for the independently retained head.

    The boolean return is intentional: an implementation that merely fetched
    bytes, logged a warning, or returned ``None`` cannot accidentally grant a
    real resume or final audit.
    """

    verifier = getattr(authority, "verify_head", None)
    if not callable(verifier):
        raise CheckpointLedgerError("a HeadAnchorAuthority is required for this operation")
    try:
        verified = verifier(expectation)
    except Exception as error:
        raise CheckpointLedgerError("external checkpoint-head anchor verification failed") from error
    if verified is not True:
        raise CheckpointLedgerError("external checkpoint-head anchor was not verified")


def create_attempt(
    ledger_path: str | Path,
    *,
    attempt_id: str,
    binding: AttemptBinding | Mapping[str, str],
    metadata: Mapping[str, Any] | None = None,
    started_at_utc: str | None = None,
) -> dict[str, Any]:
    """Create exactly one active attempt at an unused ledger path.

    The API intentionally takes hashes rather than filenames, so construction
    cannot trigger source/waveform access.
    """

    _require(isinstance(attempt_id, str) and attempt_id, "attempt_id must be a non-empty string")
    normalized_binding = _coerce_binding(binding)
    normalized_metadata = _canonical_json_value(dict(metadata or {}))
    destination = Path(ledger_path)
    if destination.exists():
        raise CheckpointLedgerError(f"attempt ledger already exists: {destination}")
    binding_sha256 = _json_sha256(normalized_binding.as_dict())
    start = _new_entry(
        sequence=0,
        event="attempt_started",
        attempt_id=attempt_id,
        binding_sha256=binding_sha256,
        previous_entry_sha256=GENESIS_PREVIOUS_SHA256,
        payload={"metadata": normalized_metadata},
        recorded_at_utc=started_at_utc,
    )
    document = _seal_document(
        {
            "format": LEDGER_FORMAT,
            "attempt_id": attempt_id,
            "binding": normalized_binding.as_dict(),
            "binding_sha256": binding_sha256,
            "metadata": normalized_metadata,
            "state": ACTIVE_STATE,
            "entries": [start],
        }
    )
    _validate_document(document)
    try:
        resolved_destination = destination.resolve(strict=False)
    except OSError as error:
        raise CheckpointLedgerError(f"cannot resolve ledger for attempt creation: {destination}") from error
    gate = _create_gate(resolved_destination, document)
    try:
        _assert_no_writer_lock(resolved_destination)
        _atomic_create_json(resolved_destination, document)
        created = verify_ledger(resolved_destination)
        _validate_gate_document(gate, created)
        return created
    finally:
        gate.release()


def resume_attempt(
    ledger_path: str | Path,
    *,
    expectation: CheckpointHeadExpectation,
    anchor_authority: HeadAnchorAuthority,
) -> dict[str, Any]:
    """Verify a resumable attempt at one exact head while no writer holds it.

    This does not itself grant ownership.  A caller must subsequently acquire
    a ``WriterLease`` and retain it through the resumed runner lifetime.
    """

    destination = Path(ledger_path)
    with checkpoint_audit_guard(destination) as gate:
        _assert_no_writer_lock(destination)
        document = verify_ledger(destination)
        _validate_gate_document(gate, document)
        _require_head_expectation(document, expectation)
        verify_head_anchor(anchor_authority, expectation)
        _require_active(document)
        return document


def _append_event(
    ledger_path: str | Path,
    *,
    binding: AttemptBinding | Mapping[str, str],
    event: str,
    payload: Mapping[str, Any] | None,
    recorded_at_utc: str | None,
    checkpoint_id: str | None = None,
    terminal_state: str | None = None,
    expected_ledger_sha256: str,
    lease: WriterLease,
) -> dict[str, Any]:
    destination = Path(ledger_path)
    if not isinstance(lease, WriterLease):
        raise CheckpointLedgerError("an exclusive WriterLease is required for every ledger update")
    with lease._write_mutex:
        document = verify_ledger(destination)
        _require_owned_writer_lease(lease, destination=destination, document=document)
        _validate_gate_document(lease._gate, document)
        _require_matching_binding(document, binding)
        _require_active(document)
        _require_expected_head(document, expected_ledger_sha256)
        if event == "checkpoint":
            existing_ids = {entry["checkpoint_id"] for entry in document["entries"] if entry["event"] == "checkpoint"}
            if checkpoint_id in existing_ids:
                raise CheckpointLedgerError(f"checkpoint_id is repeated: {checkpoint_id}")
        entry = _new_entry(
            sequence=len(document["entries"]),
            event=event,
            attempt_id=document["attempt_id"],
            binding_sha256=document["binding_sha256"],
            previous_entry_sha256=document["entries"][-1]["entry_sha256"],
            payload=payload,
            recorded_at_utc=recorded_at_utc,
            checkpoint_id=checkpoint_id,
            terminal_state=terminal_state,
        )
        updated = copy.deepcopy(document)
        updated["entries"].append(entry)
        if event == "terminal":
            updated["state"] = terminal_state
        updated = _seal_document(updated)
        _validate_document(updated)
        _atomic_replace_json(destination, updated)
        verified = verify_ledger(destination)
        _validate_gate_document(lease._gate, verified)
        return verified


def append_checkpoint(
    ledger_path: str | Path,
    *,
    binding: AttemptBinding | Mapping[str, str],
    checkpoint_id: str,
    payload: Mapping[str, Any] | None = None,
    recorded_at_utc: str | None = None,
    expected_ledger_sha256: str,
    lease: WriterLease,
) -> dict[str, Any]:
    """Append one checkpoint while the caller holds the exclusive writer lease."""

    return _append_event(
        ledger_path,
        binding=binding,
        event="checkpoint",
        checkpoint_id=checkpoint_id,
        payload=payload,
        recorded_at_utc=recorded_at_utc,
        expected_ledger_sha256=expected_ledger_sha256,
        lease=lease,
    )


def finalize_attempt(
    ledger_path: str | Path,
    *,
    binding: AttemptBinding | Mapping[str, str],
    terminal_state: str,
    payload: Mapping[str, Any] | None = None,
    recorded_at_utc: str | None = None,
    expected_ledger_sha256: str,
    lease: WriterLease,
) -> dict[str, Any]:
    """Atomically terminalize an attempt; terminal ledgers can never resume."""

    _require(terminal_state in TERMINAL_STATES, "terminal_state is not permitted")
    return _append_event(
        ledger_path,
        binding=binding,
        event="terminal",
        terminal_state=terminal_state,
        payload=payload,
        recorded_at_utc=recorded_at_utc,
        expected_ledger_sha256=expected_ledger_sha256,
        lease=lease,
    )
