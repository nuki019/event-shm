"""Send-on-delta (SoD) eventization — the core of the project.

Two layers:
  Layer A (within-record, us scale): level-crossing events of the
      compensated residual signal r(t). An event (t, +1/-1) is emitted
      when r(t) deviates from the last emitted level by +-delta.
  Layer B (across-record, days/months scale): SoD events of the damage
      index time series DI_p(k) per path p.

References
----------
Miskowicz, "Send-On-Delta Concept: An Event-Based Data Reporting
Strategy", Sensors 6(1):49-63, 2006.
"""
import numpy as np


def sod_encode(x, delta, initial=0.0):
    """Vectorized send-on-delta encoding of 1-D signal x.

    Quantized level q_i = floor(x_i/delta + 1/2); an event is emitted
    whenever the level changes. Multiple crossed levels produce multiple
    events at the same sample index (classic SoD semantics).

    Returns (t, signs, levels): event sample indices, +-1 signs, levels.
    """
    if delta <= 0:
        raise ValueError('delta must be positive')
    x = np.asarray(x, dtype=np.float64)
    q = np.floor(x / delta + 0.5).astype(np.int64)
    q0 = np.floor(initial / delta + 0.5)
    dq = np.diff(np.concatenate(([q0], q)))
    (idxs,) = np.nonzero(dq)
    if idxs.size == 0:
        return (np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int8),
                np.empty(0, dtype=np.float64))
    steps = dq[idxs]
    reps = np.abs(steps).astype(np.int64)
    t = np.repeat(idxs, reps)
    signs = np.repeat(np.sign(steps).astype(np.int8), reps)
    # levels: walk from previous level to new level in unit steps
    new_lvl = q[idxs]
    prev_lvl = new_lvl - steps
    offs = np.concatenate([np.arange(1, int(r) + 1) for r in reps]).astype(np.int64)
    sgn = np.repeat(np.sign(steps), reps)
    levels = (np.repeat(prev_lvl, reps) + offs * sgn) * delta
    return t.astype(np.int64), signs, levels


def sod_decode(t, levels, n_samples, initial=0.0):
    """Zero-order-hold reconstruction of a signal from SoD events."""
    y = np.full(n_samples, initial, dtype=np.float64)
    if len(t) == 0:
        return y
    # segments between events take the level value
    starts = np.concatenate(([0], t))
    vals = np.concatenate(([initial], levels))
    ends = np.concatenate((t, [n_samples]))
    for a, b, v in zip(starts, ends, vals):
        y[a:b] = v
    return y


def event_rate(n_events, n_samples):
    """Events per original sample (data-rate ratio vs. raw samples)."""
    return n_events / max(n_samples, 1)


def equivalent_bitrate_bits_per_sample(n_events, n_samples, ts_bits=17):
    """Approximate bits/original-sample.

    Each event: sign (1 bit) + timestamp. With delta-timestamp encoding
    (gap coding) ~ ts_bits per event is conservative for 10 MHz traces.
    """
    return n_events * (1 + ts_bits) / max(n_samples, 1)


# ---------------- Layer B: across-record SoD on DI series ----------------

def sod_series(values, delta, initial=None):
    """SoD encode a slowly-varying scalar series (e.g. DI vs record index).

    Returns (k, sign, level) events where the series crossed last +/- delta.
    """
    values = np.asarray(values, dtype=float)
    if initial is None:
        initial = values[0] if values.size else 0.0
    return sod_encode(values, delta, initial=initial)


# ---------------- Event-stream statistics for discrimination ----------------

def inter_event_intervals(t):
    return np.diff(np.sort(t)) if len(t) > 1 else np.array([])


def fano_factor(t, window):
    """Burstiness: Fano factor of event counts in fixed windows."""
    if len(t) == 0:
        return 0.0
    n_win = int(np.ceil((t.max() + 1) / window))
    counts = np.zeros(n_win)
    for w in range(n_win):
        counts[w] = np.sum((t >= w * window) & (t < (w + 1) * window))
    m = counts.mean()
    return counts.var() / m if m > 0 else 0.0
