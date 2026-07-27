"""Temperature compensation baselines: BSS (baseline signal stretch) and
OBS (optimal baseline selection), following Croxford et al., Ultrasonics 2010.
"""
import numpy as np
from scipy.signal import butter, filtfilt


def highpass(x, fs, fc=20e3, order=3):
    b, a = butter(order, fc / (fs / 2), btype='high')
    return filtfilt(b, a, x, axis=0)


def stretch_signal(y, alpha):
    """Time-stretch signal y by factor alpha (alpha>1 => longer).
    Linear interpolation resampling, output truncated/padded to len(y)."""
    n = len(y)
    t = np.arange(n)
    t_new = t / alpha  # sample positions in original time
    out = np.interp(t_new, t, y, left=y[0], right=y[-1])
    return out


def bss_compensate(x, baseline, alphas=None):
    """Baseline Signal Stretch: find stretch factor minimizing residual.

    Returns (best_alpha, stretched_baseline, residual).
    """
    if alphas is None:
        # temperature-induced stretch is tiny: +-0.5% covers ~ +/-40 degC
        alphas = np.linspace(0.995, 1.005, 81)
    best = (np.inf, 1.0, None)
    for a in alphas:
        b = stretch_signal(baseline, a)
        res = x - b
        e = float(np.dot(res, res))
        if e < best[0]:
            best = (e, a, b)
    return best[1], best[2], x - best[2]


def obs_select(x, baselines):
    """Optimal Baseline Selection: pick baseline with min residual energy.
    baselines: (K, N) array. Returns (index, baseline, residual)."""
    x = np.asarray(x)
    residuals = baselines - x[None, :]
    energies = np.einsum('ij,ij->i', residuals, residuals)
    k = int(np.argmin(energies))
    return k, baselines[k], x - baselines[k]


def obs_bss(x, baselines, alphas=None):
    """OBS followed by BSS on the selected baseline (standard combo)."""
    k, b, _ = obs_select(x, baselines)
    a, bs, r = bss_compensate(x, b, alphas)
    return k, a, bs, r
