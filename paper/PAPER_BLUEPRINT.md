# Strict Evaluation Manuscript Blueprint

This is a working blueprint, not paper prose.

## Position

The manuscript is an evaluation audit, not a claim of a new SoD sensing
principle or a deployment study. Its falsifiable conclusion is limited to the
frozen public-data protocol: bounded SoD is not the preferred codec among the
four tested codecs, and the tested cold-start alarms do not provide an
operational alarm result.

## Evaluation Audit

| Pillar | Status | Evidence |
| --- | --- | --- |
| Research gap | Covered | Previous count-matched representation comparisons omitted byte accounting, healthy-only selection, and cold-start alarm separation |
| Construction pipeline | Covered within scope | Fixed date splits, training-only quantization/baselines, validation-only selection, serialized packets, and cache manifests |
| Evaluation framework | Covered | Four hard capacities, record-level AUC with bootstrap intervals, temperature matching, full threshold grids, false calls/day, delay, coverage |
| Empirical findings | Covered | E7 and E8 full JSON outputs |
| Companion method | Not applicable | The contribution is the audit and its negative result, not an optimized new detector |

## Introduction Logic

1. Guided-wave monitoring needs representations and alarms that remain
   evaluable under environmental variation.
2. Early project comparisons used sample counts, exploratory selection, and a
   non-blind long-term replay; those properties cannot support codec or alarm
   claims.
3. The question is whether SoD remains competitive after exact packet
   accounting and frozen selection, and whether a March-calibrated alarm gives
   useful April outcomes.
4. The protocol must prevent path pseudoreplication, payload undercounting,
   label leakage, and retroactive operating-point selection.
5. The solution is a date-separated hard-cap codec benchmark plus a
   cross-month cold-start replay.
6. Contributions are the frozen protocol, the all-capacity codec result, and
   the all-threshold alarm audit.

## Section Plan

| Section | Role | Evidence |
| --- | --- | --- |
| Introduction | State the evaluation question and the narrow, falsifiable claim | E1--E6 |
| Related Work | Position SoD, compensation, and compression without novelty claims | E6 |
| Method | Define the shared residual contract, codecs, scoring, and alarm calculation | E2, E5 |
| Data | Define record-level split units and the two dataset boundaries | E2--E4, E6 |
| Experiments | State frozen selection and test gates before results | E2, E5 |
| Results | Report every capacity and every threshold-grid range | E3, E4 |
| Discussion | State the negative result and bound the conclusion | E1--E4 |
| Conclusion | Summarize the audited finding and next required evidence | E1--E4 |
