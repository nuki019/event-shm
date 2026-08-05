# Reproducibility and evidence boundary

This repository evaluates post-compensation send-on-delta (SoD) eventization
for guided-wave structural health monitoring. The strict evaluation is a
software codec and cold-start replay audit, not a deployment study.

## Environment and data

~~~powershell
conda env create -f environment.yml
conda run -n shm python -m compileall -q src
~~~

The raw archives are ignored by Git. The OGW CFRP temperature archives are
listed in data/ogw_files.json; selected UF/Utah long-term monthly files are
listed in data/longterm_selected.json. Derived residuals, caches, plots, and
all JSON results except the two hash-bound E7/E8 paper summaries are ignored
so that they are not mistaken for source data or paper evidence.

## Frozen protocol

protocols/strict_evaluation_v1.json is the only paper-eligible evaluation
path. It defines:

- 40 kHz post-compensation residual coding;
- healthy OGW train/validation/test dates of 2018-12-13--17,
  2018-12-18--19, and 2018-12-20--22;
- hard per-record capacities of 2,048, 4,096, 8,192, and 16,384 bytes;
- bounded SoD, uniform linear, PCA, and Haar DWT codecs;
- validation-only configuration selection and test-only reporting;
- March 2021 healthy calibration followed by a complete April 2021 blind
  replay;
- nine predeclared March-derived thresholds per alarm feature; and
- record-level AUC, exact serialized payload, false calls/day, newly started
  post-onset delay, record/day coverage, and temperature-support reporting.

Test labels are forbidden for codec fitting, quantizer fitting, codec
selection, alarm baseline construction, score calibration, and threshold
selection. Paths are never resampled as independent samples.

## Strict negative-result paper boundary

The active manuscript route is a strict negative-result and
applicability-boundary paper. Its evidence eligibility is frozen in
`paper/NEGATIVE_RESULT_BOUNDARY_EVIDENCE_MANIFEST.json` and explained in
`paper/EVIDENCE_MAP.md`. The manifest binds the current protocol and completed
E7/E8 JSON SHA-256 values; it records `mechanism-v2.6` only as an
exclusion-only integrity record.

Run both read-only checks before building or handing off the manuscript:

~~~powershell
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/audit_strict_evaluation.py
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/audit_negative_result_boundary.py
~~~

The boundary audit verifies current file identity, strict result-contract
consistency, and the recorded v2.6 exclusion flags. It does not prove original
execution chronology, raw-data provenance, absence of unrecorded access,
scientific generalization, or submission readiness.

## Local paper-build receipt

The release identity is deliberately anchored in two commits to avoid a
self-referential receipt. First commit the audited manuscript source, protocol,
E7/E8 summaries, manifest, and auditors as the clean source snapshot (C1).
Build from C1 with XeLaTeX and `-recorder`, then record the C1 commit/tree,
input hashes, runtime identity, and local PDF/BibTeX outputs in
`paper/NEGATIVE_RESULT_BOUNDARY_BUILD_RECEIPT.json`. Commit only that receipt
as C2 and run the boundary audit again with `--build-receipt`. The receipt
identifies one local build; it does not make the ignored PDF public, nor does
it prove an experimental chronology or submission acceptance.

## Completed full outputs

The full outputs in this checkout are:

| Artifact | Evidence |
| --- | --- |
| results/e7_strict_codec_benchmark_v1.json | Full held-out codec table, bootstrap intervals, payload summaries, model bytes, matching checks, and selected configurations |
| results/e8_cold_start_alarm_v1.json | Full April alarm grids, onset metadata, false-call intervals, delay, coverage, and temperature-support checks |

E7 has 168 healthy training records, 73 healthy validation records, 81
healthy held-out records, and 161 D04 plus 161 D24 held-out records. E8 has
15,554 March calibration records and 15,069 April records; the labelled April
transition starts at record 8,401. The manuscript reports every capacity and
the min--max range across every threshold grid rather than a retrospectively
chosen point.

Run the implementation checks:

~~~powershell
& C:\Users\wfy\.conda\envs\shm\python.exe -m unittest discover -s tests -v
& C:\Users\wfy\.conda\envs\shm\python.exe -m compileall -q src
~~~

To regenerate a frozen result:

~~~powershell
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/e7_strict_codec_benchmark.py
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/e8_cold_start_alarm.py
~~~

--smoke verifies execution only. Smoke JSON and plots cannot enter paper
tables, selection, or scientific conclusions.

## Historical diagnostics

E2--E4 and related plots remain in the repository for implementation audit.
They are not paper evidence because they predate the frozen byte-accounted and
cold-start protocol. They must not be used to choose a reported SoD threshold,
capacity, or alarm setting.

All mechanism-v2.x artifacts, including D12/D16/MORPHO history and v2.7
synthetic infrastructure, are also excluded from this paper's empirical
claims. They cannot be used as a mechanism result, external replication, or
successor authorization.

## Claim boundary

Even the completed strict evaluation does not establish multi-structure
generalization, field false-alarm calibration, endpoint hardware cost, or
population probability of detection. In particular, the April replay has one
observed labelled onset, and its post-onset alarm fields are descriptive
outcomes rather than a PoD estimate.
