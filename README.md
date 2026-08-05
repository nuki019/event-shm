# Strict Evaluation of SoD Eventization for Guided-Wave SHM

This repository contains a research audit of send-on-delta (SoD) eventization
for guided-wave structural health monitoring. It is not a deployment-ready
monitoring system and does not establish ADC, MCU, energy, latency, or field
reliability claims.

The paper source is paper/main.tex. The authoritative evaluation protocol is
protocols/strict_evaluation_v1.json.

## Current evidence status

The full strict E7 and E8 evaluations have completed. Their derived JSON and
PNG files are intentionally ignored by Git, but the completed artifacts in
this checkout are:

- results/e7_strict_codec_benchmark_v1.json
- results/e8_cold_start_alarm_v1.json
- figures/e7_strict_codec_benchmark_v1.png
- figures/e8_cold_start_alarm_v1.png

| Audit | Frozen scope | Result |
| --- | --- | --- |
| E7: byte-accounted codec benchmark | 2,048, 4,096, 8,192, and 16,384 bytes/record; bounded SoD, uniform linear interpolation, PCA, and Haar DWT | Bounded SoD has lower held-out record AUC than every general codec at every capacity for D04 and D24. |
| E8: cold-start alarm replay | March 2021 calibration, full April 2021 scoring, nine March-derived thresholds per feature | Dense residual energy: 0.897--5.144 false calls/day; Level-A SoD count: 0.897--4.964; first new alarms occur 2,556--2,585 minutes after onset. |

These results are negative findings under the frozen public-data protocol.
They are not a reason to choose a different SoD configuration after seeing
test AUC, false calls, delay, or coverage.

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
data, command, and claim boundaries.

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
