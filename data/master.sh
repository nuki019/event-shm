#!/bin/bash
# Master serial scheduler: downloads + experiments, one heavy task at a time.
PY=/c/Users/wfy/.conda/envs/shm/python.exe
cd /d/event-camera/SHM
retry() {  # retry <name> <cmd...>
  local name=$1; shift
  for attempt in $(seq 1 60); do
    echo "=== [$name] attempt $attempt $(date +%H:%M:%S) ==="
    "$@" && { echo "=== [$name] DONE ==="; return 0; }
    echo "=== [$name] rc=$? retry in 60s ==="; sleep 60
  done
}
# downloads (resume-safe)
retry D24 $PY src/data/s3_download.py 15130196 OGW_CFRP_Temperature_dam_D24.zip 14
retry D04 $PY src/data/s3_download.py 15117569 OGW_CFRP_Temperature_dam_D04.zip 14
retry LT2021_03 $PY src/data/s3_download.py 51426359 measurements_2021_03.pickle 10
retry LT2021_04 $PY src/data/s3_download.py 51426365 measurements_2021_04.pickle 10
retry LT2021_05 $PY src/data/s3_download.py 51426368 measurements_2021_05.pickle 10
# experiments
retry E1_EXTRAP $PY src/experiments/e1_extrapolation.py
echo "MASTER QUEUE DONE"
