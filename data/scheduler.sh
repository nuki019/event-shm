#!/bin/bash
# Serial experiment scheduler with memory-retry. One heavy task at a time.
PY=/c/Users/wfy/.conda/envs/shm/python.exe
cd /d/event-camera/SHM
run() {
  local name=$1; shift
  for attempt in $(seq 1 40); do
    echo "=== [$name] attempt $attempt $(date +%H:%M:%S) ==="
    $PY "$@" && { echo "=== [$name] DONE ==="; break; }
    echo "=== [$name] failed rc=$?, wait 75s ==="
    sleep 75
  done
}
run e1_extrap src/experiments/e1_extrapolation.py
run e2_syn src/experiments/e2_pareto.py --source synthetic --freq 100 --max-paths 40 --out results/e2_pareto_synthetic2.json
echo "ALL SCHEDULED TASKS DONE"
