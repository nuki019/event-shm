# Paper Evidence Map

This is a working ledger for the manuscript. It is not part of the paper
body.

| ID | Source | Level | Supports | Cannot support | Planned use | Risk |
| --- | --- | --- | --- | --- | --- | --- |
| E1 | \`suggestions.md\` | L1 | The four review failure modes and required benchmark/alarm changes | External literature claims embedded in the review | Framing and protocol motivation | Review text contains unsupported external links, so only project-specific criticisms are used |
| E2 | \`protocols/strict_evaluation_v1.json\` | L1 | Frozen dates, payload targets, selection rules, alarm calibration, metrics, and prohibited claims | Outcome values | Methods and Experiments | None for declared protocol |
| E3 | \`results/e7_strict_codec_benchmark_v1.json\` | L1 | Full held-out codec AUCs, bootstrap intervals, packet sizes, model bytes, matching checks, and selected configurations | Hardware acquisition cost or general codec ranking | Results and Discussion | One public plate and two reversible disc conditions |
| E4 | \`results/e8_cold_start_alarm_v1.json\` | L1 | Full April replay, threshold grids, false calls/day, new-alarm delay, coverage, onset metadata, and temperature-support gap | Population PoD, calibrated field FAR, or deployment readiness | Results and Discussion | One observed labelled transition |
| E5 | \`src/experiments/e7_strict_codec_benchmark.py\`, \`src/experiments/e8_cold_start_alarm.py\`, \`src/methods/strict_codecs.py\`, \`src/methods/strict_alarm.py\`, and \`tests/test_strict_evaluation.py\` | L1 | Exact implementation of leakage guards, packet serialization, capacity checks, incident accounting, and tests | Scientific performance beyond E3/E4 outputs | Methods and Reproducibility | Code confirms implementation, not effectiveness by itself |
| E6 | Crossref metadata retrieved in this session for the five cited DOIs | L3 | Existence and citation-level description of SoD, temperature-compensation, dataset, and compression references | Method or performance details not contained in titles/metadata | Introduction, Related Work, Data | Metadata-only |

## Contribution Trace

| Contribution | Manuscript location | Empirical trace | Evidence status |
| --- | --- | --- | --- |
| Frozen, byte-accounted codec protocol | Method and Experiments | Table 1 and Fig. 1 | L1 confirmed |
| Negative codec finding under all predeclared capacities | Results and Discussion | Table 1 and Fig. 1 | L1 confirmed |
| Frozen cold-start alarm audit | Method and Experiments | Table 2 and Fig. 2 | L1 confirmed |
| Deployment, energy, latency, or population PoD claim | None | None | Unsupported; excluded |
