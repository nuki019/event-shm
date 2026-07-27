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
    """Encode 1-D signal x with send-on-delta sampling.

    An event is emitted at index i whenever x[i] crosses last_level +/- delta.
    The emitted level is the crossed threshold (quantized), not x[i] itself
    (classic SoD / level-crossing with absolute criterion).

    Parameters
    ----------
    x : (N,) array
    delta : float, event threshold (must be > 0)
    initial : float, initial reference level

    Returns
    -------
    t : (M,) int array — sample indices of events
    s : (M,) int8 array — event signs (+1 up-crossing, -1 down-crossing)
    levels : (M,) float array — the quantized levels crossed
    """
    if delta <= 0:
        raise ValueError('delta must be positive')
    x = np.asarray(x)
    idx = []
    signs = []
    levels = []
    last = initial
    # vectorized inner loop is hard due to state dependence; use numpy where possible.
    # For SHM residual signals (N ~ 10k-100k) a python loop is acceptable,
    # but we accelerate by jumping: compute deviation from `last`, find first crossing.
    N = x.shape[0]
    i = 0
    while True:
        dev = x[i:] - last
        cross = np.nonzero(np.abs(dev) >= delta)[0]
        if cross.size == 0:
            break
        j = i + cross[0]
        d = dev[cross[0]]
        n_steps = int(abs(d) // delta)          # multiple levels can be crossed at once
        step = delta if d > 0 else -delta
        for k in range(1, n_steps + 1):
            idx.append(j)
            signs.append(1 if step > 0 else -1)
            levels.append(last + k * step)
        last = last + n_steps * step
        i = j + 1
        if i >= N:
            break
    return np.asarray(idx, dtype=np.int64), np.asarray(signs, dtype=np.int8), np.asarray(levels)


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
