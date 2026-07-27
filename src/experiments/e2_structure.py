"""E2b: eventization advantage via STRUCTURE — localization, not just detection.

Detection at high rate is trivial for both. The event advantage shows in
tasks needing the damage wavepacket's time structure: coarse localization
from event-cluster arrival times. Compare SoD events vs matched-rate
uniform decimation on localization error of the damage position.
Synthetic proof-of-concept.
"""
import sys, os, json, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.synthetic import make_cycle, DAMAGE_POS, RNG_POS
from src.methods.baseline_fast import bss_search
from src.methods.sod import sod_encode
from sklearn.metrics import roc_auc_score


def localize_from_events(resid, delta, positions, paths):
    """Estimate damage position: weight each path's earliest strong event
    time -> triangulate via path midpoint proximity. Return (est, n_ev)."""
    P = len(paths)
    first_t = np.full(P, np.inf)
    strength = np.zeros(P)
    for p in range(P):
        t, s, lv = sod_encode(resid[p], delta)
        if len(t):
            first_t[p] = t[0]
            strength[p] = len(t)
    # use top-k active paths; estimate = weighted mean of path midpoints
    k = max(3, P // 6)
    top = np.argsort(strength)[::-1][:k]
    w = strength[top] + 1e-9
    mids = np.array([(positions[paths[p][0]] + positions[paths[p][1]]) / 2 for p in top])
    est = (mids * w[:, None]).sum(0) / w.sum()
    return est, int(strength.sum())


def localize_from_uniform(resid, step, positions, paths):
    """Same localization but residual recovered from uniformly decimated samples."""
    P, N = resid.shape
    rec = np.zeros_like(resid)
    rec[:, ::step] = resid[:, ::step]
    strength = np.abs(rec).sum(axis=1)
    first_t = np.full(P, np.inf)
    for p in range(P):
        nz = np.nonzero(np.abs(rec[p]) > 0.05)[0]
        if len(nz): first_t[p] = nz[0]
    k = max(3, P // 6)
    top = np.argsort(strength)[::-1][:k]
    w = strength[top] + 1e-9
    mids = np.array([(positions[paths[p][0]] + positions[paths[p][1]]) / 2 for p in top])
    est = (mids * w[:, None]).sum(0) / w.sum()
    return est


def run(delta=0.05, seed=0):
    ud = make_cycle(n_temps=5, t_lo=20, t_hi=28, freqs=[100], damaged=False, seed=seed)
    dm = make_cycle(n_temps=5, t_lo=20, t_hi=28, freqs=[100], damaged=True, seed=seed+1)
    freq = 100
    B = np.transpose(np.stack([ud['signals'][(freq, ti)] for ti in range(5)]), (1, 0, 2))
    alphas = np.linspace(0.995, 1.005, 9)
    paths = ud['paths']; pos = ud['positions']
    errs_ev, errs_un, rates = [], [], []
    for ti in range(5):
        X = dm['signals'][(freq, ti)]
        R = np.empty_like(X)
        for p in range(X.shape[0]):
            _, _, _, r = bss_search(X[p], B[p], alphas)
            R[p] = r
        est_e, n_ev = localize_from_events(R, delta, pos, paths)
        rate = n_ev / (X.shape[0] * X.shape[1])
        step = max(1, int(round(1.0 / max(rate, 1e-6))))
        est_u = localize_from_uniform(R, step, pos, paths)
        errs_ev.append(np.linalg.norm(est_e - DAMAGE_POS))
        errs_un.append(np.linalg.norm(est_u - DAMAGE_POS))
        rates.append(rate)
    return np.mean(errs_ev), np.mean(errs_un), np.mean(rates)


if __name__ == '__main__':
    rows = []
    for delta in [0.02, 0.05, 0.1, 0.2]:
        ee, eu, rate = run(delta)
        rows.append({'delta': delta, 'rate': rate, 'loc_err_event_mm': ee, 'loc_err_uniform_mm': eu})
        print(f'delta={delta}: rate={rate:.4f} loc_err event={ee:.1f}mm vs uniform={eu:.1f}mm', flush=True)
    json.dump(rows, open('results/e2_structure.json', 'w'), indent=1)
    print('saved')
