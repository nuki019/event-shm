# mechanism-v2 Historical Runbook (Do Not Run)

**Status: historical and disabled.** This file is retained only to explain
the origin of prior scripts and receipts. It does not authorize downloads,
schema inspection, waveform access, scoring, auditing, retry, resume, or
renaming of any mechanism-v2.x artifact.

## Why It Is Disabled

- `mechanism-v2.5` was invalidated after its frozen terminal-hold contract
  failed on the one permitted D12 confirmation.
- `mechanism-v2.6` was invalidated after an out-of-order D16 output and an
  interrupted MORPHO attempt with no auditable resume path, complete result,
  or matching auditor.
- D12, D16, MORPHO, D04/D24, COQTEL, and the listed historical long-term
  sources are not fresh blind-confirmation inputs for a successor.

The authoritative preservation record is
[`protocols/mechanism_v2_6_invalidation_receipt.json`](protocols/mechanism_v2_6_invalidation_receipt.json).
Its prohibitions take precedence over every historical command that once
appeared here or in a legacy script.

## Current Boundary

The only active implementation work is synthetic, zero-waveform v2.7
infrastructure. Its boundary is documented in
[`MECHANISM_V2_7_PRE_ACCESS_PLAN.md`](MECHANISM_V2_7_PRE_ACCESS_PLAN.md).
Candidate-source status is separately recorded in
[`protocols/mechanism_v2_7_candidate_source_screening_2026-08-05.md`](protocols/mechanism_v2_7_candidate_source_screening_2026-08-05.md).

No v2.7 protocol, data manifest, result schema, source receipt, freeze
receipt, or runner exists yet. Creating one requires a new source that passes
the pre-access license, semantic-label, raw-waveform, independent-group, and
integrity-metadata gates.

## Historical Traceability

Legacy `download_mechanism_v2*`, `e9_mechanism_v2*`, and
`audit_mechanism_v2*` files remain in the repository as evidence of the
invalidated history. They must not be invoked as a recovery mechanism. Tests
may exercise synthetic fixtures only; passing a test is not data authorization
or mechanism evidence.
