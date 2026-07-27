"""Temperature-vs-damage discrimination from event-stream structure.

Physics priors:
  temperature drift -> events on (nearly) ALL paths, synchronized, slow,
      event rate modulated by |dT/dt|;
  damage -> events on a path SUBSET, sudden onset, persistent,
      spatially consistent with damage-path geometry.

Rule-based score: combine cross-path coherence (temperature) against
localized burst persistence (damage).
"""
import numpy as np


def cross_path_coherence(event_counts_per_path, thresh=1):
    """Fraction of paths with >= thresh events in the record window.
    High coherence (~1) => global cause (temperature); low => local (damage)."""
    counts = np.asarray(event_counts_per_path, dtype=float)
    return float(np.mean(counts >= thresh))


def burst_onset(di_events_t):
    """Suddenness of layer-B DI event onset: 1 / normalized median gap
    between the first few events (small gap => sudden)."""
    if len(di_events_t) < 3:
        return 0.0
    gaps = np.diff(di_events_t[:8]).astype(float)
    med = np.median(gaps)
    span = di_events_t[-1] - di_events_t[0] + 1e-9
    return float(np.clip(1.0 - med / (span + 1e-9), 0, 1))


def path_localization_index(event_counts_per_path, top_frac=0.1):
    """Gini-like concentration: 1.0 = all events on one path, 0 = uniform."""
    c = np.sort(np.asarray(event_counts_per_path, dtype=float))[::-1]
    if c.sum() == 0:
        return 0.0
    k = max(1, int(len(c) * top_frac))
    return float(c[:k].sum() / c.sum())


def discriminate(event_counts_per_path, coherence_w=1.0):
    """Return score>0 for temperature-like, <0 for damage-like, plus parts."""
    coh = cross_path_coherence(event_counts_per_path)
    loc = path_localization_index(event_counts_per_path)
    score = coherence_w * coh - loc
    return score, {'coherence': coh, 'localization': loc}
