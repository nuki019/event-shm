"""E3-arrival: temperature-vs-damage via event ARRIVAL-TIME structure.

Physics: temperature compensation residual events occur at (nearly) the
same delay across paths (global coherent), whereas damage scattering
events arrive at path-geometry-dependent times (dispersed). Feature:
cross-path dispersion (std) of the first strong-event arrival per path.
"""
import sys, os, json, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSetZip
from src.methods.baseline_fast import stretch_batch
from src.methods.sod import sod_encode
from sklearn.metrics import roc_auc_score


def features(x, Bpool, alphas, delta):
    """Return per-record features from event structure across 66 paths."""
    K, C, N = Bpool.shape
    first_t = np.full(C, np.nan)
    n_ev = np.zeros(C)
    di = np.zeros(C)
    for c in range(C):
        best = np.inf; br = None
        for a in alphas:
            S = stretch_batch(Bpool[:, c, :], a)
            R = S - x[c][None, :]
            e = np.einsum('ij,ij->i', R, R)
            k = int(np.argmin(e))
            if e[k] < best: best = float(e[k]); br = R[k]
        di[c] = best / max(float(np.dot(x[c], x[c])), 1e-9)
        t, s, lv = sod_encode(br, delta)
        if len(t):
            first_t[c] = t[0]
            n_ev[c] = len(t)
    act = ~np.isnan(first_t)
    frac_active = act.mean()
    arrival_std = np.nanstd(first_t) if act.sum() > 2 else 0.0
    # coherence: fraction of active paths whose first arrival within +-5% of median
    if act.sum() > 2:
        med = np.nanmedian(first_t)
        sync = np.mean(np.abs(first_t[act] - med) <= 0.05 * N)
    else:
        sync = 0.0
    return {'di_mean': float(di.mean()), 'di_max': float(di.max()),
            'frac_active': float(frac_active), 'arrival_std': float(arrival_std),
            'sync_frac': float(sync), 'n_events': float(n_ev.sum())}


def run(freq=100, delta=0.03, n_rec=None):
    ud = OGWSetZip('OGW_CFRP_Temperature_udam.zip')
    Tud = ud.temperatures()
    pool_idx = np.where(Tud <= 40.0)[0][::8][:12]
    Bpool = np.stack([ud.signals(int(i), freq) for i in pool_idx])
    alphas = np.linspace(0.995, 1.005, 9)
    M = min(n_rec, len(ud)) if n_rec else len(ud)
    H = [features(ud.signals(m, freq), Bpool, alphas, delta) for m in range(M)]
    print(f'healthy {len(H)}', flush=True)
    dm = OGWSetZip('OGW_CFRP_Temperature_dam_D24.zip')
    Md = min(n_rec, len(dm)) if n_rec else len(dm)
    D = [features(dm.signals(m, freq), Bpool, alphas, delta) for m in range(Md)]
    print(f'D24 {len(D)}', flush=True)
    json.dump({'healthy': H, 'D24': D}, open(f'results/e3_arrival_f{freq}.json', 'w'))
    y = np.array([0]*len(H) + [1]*len(D))
    for key in ['di_mean', 'frac_active', 'arrival_std', 'sync_frac', 'n_events']:
        hv = np.array([r[key] for r in H+D])
        # damage if larger for di/arrival; smaller for sync/coh
        for sign in [1, -1]:
            auc = roc_auc_score(y, sign * hv)
            if auc > 0.6:
                print(f'  {key} (sign {sign}): AUC {auc:.3f}')


if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(n_rec=n)
