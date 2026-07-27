#!/bin/bash
# Retry a python experiment on MemoryError until it fits in the memory window.
PY=/c/Users/wfy/.conda/envs/shm/python.exe
SCRIPT=$1; shift
for attempt in $(seq 1 30); do
  echo "=== attempt $attempt: $SCRIPT $@ ==="
  $PY "$SCRIPT" "$@"
  rc=$?
  if [ $rc -eq 0 ]; then echo "=== SUCCESS ==="; break; fi
  echo "=== rc=$rc, waiting 90s for memory window ==="
  sleep 90
done
