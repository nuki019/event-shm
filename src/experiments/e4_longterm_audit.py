"""Auditable descriptive Level-B result for the available 2021-04 month.

The previous E4 headline mixed exploratory detectors.  This script makes only
the reproducible claim supported by the cached event-count array: per-path
event-count streams can be eventized and their healthy/damaged descriptive
statistics can be reported.  It intentionally does not produce a deployment
false-alarm or latency claim because a threshold calibrated on an independent
healthy period is not available in this checkout.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


EVENT_COUNTS = Path("results/e4v3_EC_2021_04.npy")
TAGS = Path("results/e4v3_tag_2021_04.npy")
OUT = Path("results/e4_longterm_audit.json")


def sod_series_count(values: np.ndarray, delta: float) -> int:
    q = np.floor(np.asarray(values, dtype=np.float64) / delta + 0.5).astype(np.int64)
    return int(np.abs(np.diff(np.concatenate(([q[0]], q)))).sum())


def main() -> None:
    counts = np.load(EVENT_COUNTS)
    tags = np.load(TAGS)
    onset_indices = np.flatnonzero(tags > 0)
    if onset_indices.size == 0:
        raise RuntimeError("the selected month has no labelled damage onset")
    onset = int(onset_indices[0])
    healthy = counts[:onset]
    damaged = counts[onset:]
    # A calibration-only scale for a descriptive compression calculation, not a detector threshold.
    calibration = healthy[: min(4200, len(healthy))]
    deltas = np.maximum(1.0, np.quantile(calibration, 0.95, axis=0) - np.median(calibration, axis=0))
    event_counts = [sod_series_count(counts[:, path], float(delta)) for path, delta in enumerate(deltas)]

    payload = {
        "protocol": {
            "month": "2021_04",
            "source": "e4v3 per-record, per-path level-A SoD event counts",
            "labelled_onset_record": onset,
            "descriptive_only": True,
            "caveat": "No independent healthy calibration month is used here; this artifact must not be interpreted as a deployment false-alarm-rate or latency evaluation.",
        },
        "shape": [int(v) for v in counts.shape],
        "healthy_records": int(len(healthy)),
        "damaged_records": int(len(damaged)),
        "per_path_mean_healthy": [float(v) for v in healthy.mean(axis=0)],
        "per_path_mean_damaged": [float(v) for v in damaged.mean(axis=0)],
        "mean_ratio_damaged_to_healthy": [
            float(damaged[:, path].mean() / healthy[:, path].mean()) if healthy[:, path].mean() > 0 else None
            for path in range(counts.shape[1])
        ],
        "level_b_calibration_deltas": [float(v) for v in deltas],
        "level_b_events_per_path": event_counts,
        "level_b_total_events": int(sum(event_counts)),
        "level_b_path_record_compression": float(counts.size / max(sum(event_counts), 1)),
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"onset={onset}; Level-B events={payload['level_b_total_events']}; "
        f"path-record compression={payload['level_b_path_record_compression']:.1f}x"
    )
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
