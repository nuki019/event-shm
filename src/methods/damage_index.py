"""Damage indices (DI) for guided-wave residual signals."""
import numpy as np


def di_residual_energy(x, residual):
    """Normalized residual energy: ||r||^2 / ||x||^2."""
    den = float(np.dot(x, x))
    return float(np.dot(residual, residual)) / den if den > 0 else 0.0


def di_correlation(x, baseline_comp):
    """1 - Pearson correlation between current signal and compensated baseline."""
    a = x - x.mean()
    b = baseline_comp - baseline_comp.mean()
    den = np.linalg.norm(a) * np.linalg.norm(b)
    return 1.0 - float(np.dot(a, b) / den) if den > 0 else 1.0


def di_windowed_max(residual, fs, t0_us, t1_us):
    """Max |residual| in a time window [t0_us, t1_us] (microseconds)."""
    i0, i1 = int(t0_us * fs / 1e6), int(t1_us * fs / 1e6)
    seg = residual[i0:i1]
    return float(np.max(np.abs(seg))) if seg.size else 0.0
