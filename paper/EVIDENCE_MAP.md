# Strict Negative-Result Paper Evidence Map

This is the working evidence ledger for the manuscript. It is not part of the
paper body and does not authorize new data access or a mechanism-v2.7 run.

## Eligibility rule

Only `strict-evaluation-v1`, its completed E7 result, and its completed E8
result may support empirical paper claims. The v2.6 invalidation receipt is
included only to exclude the historical mechanism chain from the paper; it is
not a negative performance result, a mechanism result, or an external
confirmation. The companion manifest and read-only auditor make this boundary
machine-checkable against the current files.

| ID | Source | Level | Supports | Cannot support | Planned use | Risk |
| --- | --- | --- | --- | --- | --- | --- |
| B0 | `paper/NEGATIVE_RESULT_BOUNDARY_EVIDENCE_MANIFEST.json` and `src/experiments/audit_negative_result_boundary.py` | L1 | Current hashes, the E7/E8-only eligibility rule, and v2.6 exclusion flags | Original execution chronology, raw-data provenance, absence of unrecorded access, or submission readiness | Reproducibility appendix and internal release check | It is a present-day evidence-binding audit, not a historical rerun receipt |
| B1 | `protocols/strict_evaluation_v1.json`, SHA-256 `9c780aee880c46580978d949c737573d59a9eee7092d9b90fc64a56d99858154` | L1 | Frozen dates, payload targets, selection rules, alarm calibration, metrics, and prohibited claims | Outcome values | Methods and Experiments | None for the declared protocol |
| B2 | `results/e7_strict_codec_benchmark_v1.json`, SHA-256 `5b44ff3fbdd30a07101c0c2971455f8ed56bda1e41ba7b050eec2f75896638fa` | L1 | Full held-out codec AUCs, bootstrap intervals, packet sizes, model bytes, matching checks, and selected configurations | Hardware acquisition cost, general codec ranking, or multi-structure generalization | Results and Discussion | One declared plate and two reversible disc conditions |
| B3 | `results/e8_cold_start_alarm_v1.json`, SHA-256 `53228251c6607e01b17288a4723ba60d0201eb0d81f62463820871d684c49e94` | L1 | Full April replay, threshold grids, false calls/day, new-alarm delay, coverage, onset metadata, and temperature-support gap | Population PoD, calibrated field FAR, or deployment readiness | Results and Discussion | One observed labelled transition |
| B4 | `src/experiments/audit_strict_evaluation.py`, E7/E8 implementation, strict methods, and tests | L1 | Implementation of leakage guards, packet serialization, capacity checks, incident accounting, and result-artifact consistency checks | Scientific effectiveness beyond B2/B3 or proof of full execution chronology | Methods and Reproducibility | Passing code is not an empirical result |
| B5 | `protocols/mechanism_v2_6_invalidation_receipt.json`, SHA-256 `c65d281b3e9bf3c5c841ed052b8ba258cee9e92f578982da0ada3655e3b79a1d` | L1 | Exclusion of v2.6 D16/MORPHO and associated mechanism-chain artifacts from paper claims | Codec performance, a scientific negative result, mechanism, external confirmation, or a successor authorization | Scope boundary only | Must never enter a result table, figure, or parameter choice |
| B6 | E2--E6 logs, early PCA outputs, early long-term replays, and v2.7 synthetic tests | Mixed historical / engineering | Implementation diagnostics and future engineering context | Paper results, parameter selection, independent replication, or data qualification | Excluded from manuscript evidence | Mixed provenance and/or no real-waveform result |
| B7 | Independently checked metadata for the five cited DOIs | L3 | Citation-level identification of SoD, temperature compensation, compression, and the two datasets | Detailed prior-method claims, performance comparisons, or local record counts | Introduction, Related Work, and dataset attribution | Metadata-only; prose is restricted to citation-level statements |

## Contribution trace

| Contribution | Manuscript location | Empirical trace | Evidence status |
| --- | --- | --- | --- |
| Frozen, byte-accounted evaluation contract | Method and Experiments | B1, B4 | L1 confirmed |
| E7 codec applicability boundary | Results and Discussion | Table 1 and Fig. 1; B2 | L1 confirmed, within one plate / D04 / D24 |
| E8 cold-start alarm applicability boundary | Results and Discussion | Table 2 and Fig. 2; B3 | L1 confirmed, within one observed transition |
| Evidence-eligibility rule excluding invalidated mechanism artifacts | Method, Experiments, and Discussion | B0 and B5 | L1 confirmed as an integrity boundary, not a scientific result |
| General SoD, mechanism, external-confirmation, deployment, energy, latency, field-FAR, or population-PoD claim | None | None | Unsupported and excluded |

## Required verification before a paper build or handoff

```powershell
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/audit_strict_evaluation.py
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/audit_negative_result_boundary.py
```

The first command checks the strict result contract. The second checks the
current evidence identity and paper-route exclusion rule. Neither command
turns an audit pass into proof of chronology, provenance, or generalization.

For a release snapshot, commit the clean audited source set first (C1). Build
the paper locally from C1 with XeLaTeX and `-recorder`, then create the
ignored-PDF receipt `paper/NEGATIVE_RESULT_BOUNDARY_BUILD_RECEIPT.json` with
the C1 commit/tree, exact input hashes, runtime identity, and output hashes.
Commit the receipt alone as C2 and run the boundary audit from C2 with
`--build-receipt`. This two-commit sequence anchors the local build without
making the PDF itself a public repository artifact.
