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
listed in data/longterm_selected.json. Derived residuals, caches, JSON
results, and plots are also ignored so that they are not mistaken for source
data.

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

## Claim boundary

Even the completed strict evaluation does not establish multi-structure
generalization, field false-alarm calibration, endpoint hardware cost, or
population probability of detection. In particular, the April replay has one
observed labelled onset, and its post-onset alarm fields are descriptive
outcomes rather than a PoD estimate.
