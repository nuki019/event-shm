# Applicability Boundaries of SoD Eventization for Guided-Wave SHM

This repository contains a research audit of send-on-delta (SoD) eventization
for guided-wave structural health monitoring. It is not a deployment-ready
monitoring system and does not establish ADC, MCU, energy, latency, or field
reliability claims.

The paper source is paper/main.tex. The authoritative evaluation protocol is
protocols/strict_evaluation_v1.json.

## Current evidence status

The full strict E7 and E8 evaluations have completed. The two frozen result
summaries and the two manuscript figures are versioned for the paper
snapshot; raw archives and all other derived outputs remain ignored:

- results/e7_strict_codec_benchmark_v1.json
- results/e8_cold_start_alarm_v1.json
- paper/e7_strict_codec_benchmark_v1.png
- paper/e8_cold_start_alarm_v1.png

| Audit | Frozen scope | Result |
| --- | --- | --- |
| E7: byte-accounted codec benchmark | 2,048, 4,096, 8,192, and 16,384 bytes/record; bounded SoD, uniform linear interpolation, PCA, and Haar DWT | Bounded SoD has lower held-out record AUC than every general codec at every capacity for D04 and D24. |
| E8: cold-start alarm replay | March 2021 calibration, full April 2021 scoring, nine March-derived thresholds per feature | Dense residual energy: 0.897--5.144 false calls/day; Level-A SoD count: 0.897--4.964; first new alarms occur 2,556--2,585 minutes after onset. |

These results are negative findings under the frozen declared-data protocol.
They are not a reason to choose a different SoD configuration after seeing
test AUC, false calls, delay, or coverage.

## Current paper route: strict negative result and applicability boundary

The repository now advances the completed E7/E8 work as a strict
negative-result/applicability-boundary paper. E7 and E8 are the only
paper-eligible empirical results. The corresponding evidence ledger,
hash-bound manuscript-input manifest, and read-only boundary audit are:

- `paper/NEGATIVE_RESULT_BOUNDARY_PAPER_PLAN.md`
- `paper/NEGATIVE_RESULT_BOUNDARY_EVIDENCE_MANIFEST.json`
- `paper/NEGATIVE_RESULT_BOUNDARY_BUILD_RECEIPT.json` (created only after
  the committed source snapshot has been built)
- `paper/EVIDENCE_MAP.md`
- `src/experiments/audit_negative_result_boundary.py`

`mechanism-v2.6` is invalidated. Its D16/MORPHO artifacts and all historical
mechanism-chain outputs are exclusion-only integrity history: they cannot be
recast as negative findings, mechanism evidence, external confirmation, or
paper parameters. Synthetic v2.7 infrastructure likewise has no empirical
paper role.

Check the completed artifacts, manuscript input closure, and exclusion rule
without reading raw waveforms. Before the source snapshot is committed, add
`--allow-dirty`; the default command intentionally requires a clean worktree.

~~~powershell
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/audit_strict_evaluation.py
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/audit_negative_result_boundary.py --allow-dirty
~~~

## Integrity gates

The strict protocol prevents four failure modes:

1. **Data leakage:** training, validation, and held-out dates are separated;
   codec fitting, quantizer fitting, operating-point selection, alarm
   calibration, and threshold selection cannot use test labels.
2. **Metric misuse:** the unit of analysis is a monitoring record, not an
   individual path; cold-start reporting uses false calls/day, newly started
   post-onset delay, and coverage rather than population PoD.
3. **Weak benchmark design:** all codecs serialize actual packets under the
   same hard record capacity, and PCA decoder bytes are reported separately.
4. **Post-hoc selection:** all four capacities and all nine threshold points
   are reported. Historical E2--E4 outputs are exploratory diagnostics only.

## Reproduce

Create the environment:

~~~powershell
conda env create -f environment.yml
conda run -n shm python -m compileall -q src
~~~

Run the unit tests:

~~~powershell
& C:\Users\wfy\.conda\envs\shm\python.exe -m unittest discover -s tests -v
~~~

The following commands rebuild the frozen E7 and E8 outputs when the required
raw archives and caches are present:

~~~powershell
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/e7_strict_codec_benchmark.py
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/e8_cold_start_alarm.py
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/audit_strict_evaluation.py
~~~

Re-running an experiment is reproducibility work, not authorization to
retune a configuration. A changed protocol requires a new versioned protocol
file and a clearly separated result.

See RUN_STRICT_EVALUATION.md for the result audit and REPRODUCIBILITY.md for
data, command, and claim boundaries. See RUN_MECHANISM_V2.md only for the
disabled historical mechanism route.

## Repository layout

~~~text
protocols/strict_evaluation_v1.json       frozen protocol
src/methods/strict_codecs.py              hard-cap codec implementations
src/methods/strict_alarm.py               cold-start alarm metrics
src/experiments/e7_strict_codec_benchmark.py
src/experiments/e8_cold_start_alarm.py
tests/test_strict_evaluation.py
paper/                                     manuscript and paper figures
~~~

## Non-claims

The repository does not establish:

- generalization to independently instrumented structures, materials,
  sensors, or damage morphologies;
- calibrated field false-alarm or time-to-detection guarantees;
- probability of detection from the one observed April transition;
- embedded MCU memory, energy, throughput, or end-to-end latency;
- superiority to all adaptive, learned, or task-specific dense pipelines.
