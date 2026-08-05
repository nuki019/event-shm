# Strict Evaluation Run Audit

protocols/strict_evaluation_v1.json is the source of truth. It was frozen to
prevent data leakage, metric misuse, weak compression baselines, and
post-hoc operating-point selection.

## Completed full run

The formal full outputs are not smoke outputs:

| Experiment | JSON | Plot | Status |
| --- | --- | --- | --- |
| E7 codec benchmark | results/e7_strict_codec_benchmark_v1.json | figures/e7_strict_codec_benchmark_v1.png | Complete |
| E8 cold-start alarm | results/e8_cold_start_alarm_v1.json | figures/e8_cold_start_alarm_v1.png | Complete |

E7 reports all four capacities. Bounded SoD has D04 AUC 0.535--0.552 and D24
AUC 0.546--0.581; uniform linear, PCA, and Haar DWT are higher at every
reported capacity. Every observed packet stays within the declared target,
and decoder model bytes are reported separately.

E8 reports all nine March-derived thresholds for both feature families. The
false-call range is 0.897--5.144 calls/day for dense residual energy and
0.897--4.964 calls/day for Level-A SoD count. Newly started post-onset alarms
occur 2,556.2--2,584.8 minutes after the April labelled onset; these are not
PoD estimates.

## System boundary

The codec experiment is post-compensation waveform coding with a fixed
signed-16-bit software storage contract. It does not measure original ADC
acquisition, MCU runtime, energy, or hardware latency.

The alarm experiment is a software replay of OBS+BSS plus an event-count
alarm. March 2021 is fully healthy calibration data; April 2021 is scored
before labels are accessed for reporting. A pre-onset incident cannot be
credited as a new detection.

## Commands

~~~powershell
& C:\Users\wfy\.conda\envs\shm\python.exe -m unittest discover -s tests -v
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/e7_strict_codec_benchmark.py
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/e8_cold_start_alarm.py
& C:\Users\wfy\.conda\envs\shm\python.exe src/experiments/audit_strict_evaluation.py
~~~

The last command is read-only: it checks that the completed JSON artifacts
contain every declared capacity and threshold, obey hard packet caps, and
trace each selected codec descriptor to its validation audit. It is an
artifact-consistency check, not proof of execution chronology or of the
absence of hidden data access.

Do not alter configurations after inspecting the result JSON. Any protocol
revision must create a new protocol identifier and a separately labelled
evaluation.
