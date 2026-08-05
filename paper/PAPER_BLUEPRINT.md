# Strict Negative-Result and Applicability-Boundary Manuscript Blueprint

This is a working blueprint, not paper prose or a new experimental protocol.
The current paper route is independent of mechanism-v2.7 and uses only the
completed strict E7/E8 evidence.

## Position

The manuscript is an evaluation audit and applicability-boundary paper, not a
claim of a new SoD sensing principle, a physical failure mechanism, external
confirmation, or a deployment study. Its falsifiable conclusion is limited to
the frozen declared-data contract: bounded SoD does not lead held-out record
AUC among the four tested codecs, and the tested cold-start alarms cannot
establish an operational-alarm claim.

## Research questions and findings

| Question | Evidence path | Scope-bounded finding |
| --- | --- | --- |
| RQ1: Under a fixed per-record byte capacity, how does bounded SoD compare with the three implemented codecs on held-out OGW records? | E7, four capacities, D04/D24 | Bounded SoD does not lead at any declared capacity or either held-out condition. |
| RQ2: What alarm outcomes appear when March-only calibration is replayed over April? | E8, two features, nine frozen thresholds | Neither feature supports an operational-alarm claim under the reported false calls, newly started delay, and coverage. |
| RQ3: What does the combined evidence permit and exclude? | E7/E8 eligibility rule and data boundaries | The two audits delimit software applicability in their declared settings; they are not pooled mechanism evidence, external replication, or deployment validation. |

## Evaluation-paper completeness audit

| Pillar | Status | Evidence | Boundary |
| --- | --- | --- | --- |
| Research gap | Covered within this audit | Historical project diagnostics and the frozen protocol identify payload accounting, selection, unit-of-analysis, and cold-start gaps | Does not establish a complete literature taxonomy |
| Evaluation construction | Covered within scope | Fixed date splits, healthy-only fitting, actual serialization, and complete grids | Does not construct a multi-structure benchmark |
| Evaluation framework | Covered | Four hard capacities, record-level AUC, matching diagnostics, false calls/day, delay, coverage | Bootstrap is not cross-structure inference |
| Empirical findings | Covered but narrow | E7 and E8 full JSON outputs | One plate, two reversible conditions, one observed transition |
| Companion method | Not applicable | No unverified remedy is presented | Do not invent a method or use the invalidated mechanism chain |

## Evidence eligibility

| Category | Permitted role | Prohibited role |
| --- | --- | --- |
| E7/E8 under `strict-evaluation-v1` | The only empirical evidence in the manuscript | General SoD, deployment, field-FAR, or population-PoD claims |
| Strict result and boundary auditors | Reproducibility and current-artifact checks | Proof of original chronology or unrecorded-access absence |
| E2--E6 and early PCA / long-term outputs | Historical implementation diagnostics | Tables, figures, parameter choices, or scientific conclusions |
| mechanism-v2.x, D12/D16/MORPHO, and v2.7 infrastructure | Exclusion or engineering history only | Mechanism, external confirmation, performance, or new data authorization |

## Section plan

| Section | Role | Evidence |
| --- | --- | --- |
| Introduction | Define RQ1--RQ3 and the narrow, falsifiable contribution | B1--B3, B7 |
| Related Work | Position compensation, event reporting, and compression without priority or performance claims | B7 |
| Method | State evidence eligibility, system boundary, codec and alarm contracts | B0, B1, B4, B5 |
| Data | State record-level units and separate validity limits for each source | B1--B3, B7 |
| Experiments | State frozen selection, full-grid reporting, and audit limits | B0, B1, B4, B5 |
| Results | Report every capacity and every threshold-grid range | B2, B3 |
| Discussion | Interpret the negative result, non-combination rule, and applicability boundary | B0--B5 |
| Conclusion | Answer RQ1--RQ3 and name the minimum future evidence | B1--B5 |

## Pre-submission gates

1. Re-run the two read-only audits on the exact E7/E8 files and record their
   hashes; an audit pass remains a structural check, not a chronology proof.
2. Verify each cited source independently and keep metadata-only references at
   citation-level wording.
3. Ensure every numerical claim traces to E7/E8, not a historical diagnostic
   or mechanism artifact.
4. Compile and visually inspect the PDF from a clean working directory.
5. Do not call the paper submission-ready until the venue template, data/code
   availability statement, and final author metadata are complete.
