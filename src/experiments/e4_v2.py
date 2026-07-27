"""E4 v2 (long-term): within-month damage-onset detection.

Uses temperature-matched OBS baseline drawn from the SAME month's early
healthy records (avoids cross-month drift). DI(k) -> per-path z-score vs
early-healthy stats -> detection = >=K paths simultaneously elevated for a
sustained window. Reports latency & false-alarm rate on a healthy month.
"""
import sys, os, json, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.longterm_loader import load_month, PATHS


def di_month(month, n_base=150, temp_bin=2.0):
    d = load_month(month)
    gw, temp, tag = d['gw'], d['temp'], d['damage']
    M, P, N = gw.shape
    healthy = np.where(tag == 0)[0]
    base = healthy[:n_base]
    BT = temp[base]
    DI = np.empty((M, P), dtype=np.float32)
    for m in range(M):
        cand = base[np.abs(BT - temp[m]) <= temp_bin]
        if len(cand) == 0: cand = base
        for p in range(P):
            x = gw[m, p]
            best = np.inf; xx = max(float(np.dot(x, x)), 1e-9)
            for cb in range(0, len(cand), 15):
                ch = cand[cb:cb+15]
                R = gw[ch, p] - x[None, :]
                e = np.einsum('ij,ij->i', R, R)
                k = float(e.min())
                if k < best: best = k
            DI[m, p] = best / xx
    return d, DI, healthy


def detect(DI, healthy, n_warm=300, z=4.0, K=2, win=100):
    M, P = DI.shape
    warm = DI[:n_warm]
    mu, sd = warm.mean(0), warm.std(0) + 1e-9
    Z = (DI - mu) / sd
    above = (Z > z)
    n_above = above.sum(1)
    # sustained: n_above>=K for a rolling window
    det = np.zeros(M, bool)
    for m in range(M):
        a = max(0, m - win)
        det[m] = (n_above[a:m+1] >= K).mean() > 0.5
    idx = np.where(det)[0]
    return int(idx[0]) if len(idx) else None, Z


def run(month, warm=300):
    t0 = time.time()
    d, DI, healthy = di_month(month)
    onset_arr = np.where(d['damage'] > 0)[0]
    true_onset = int(onset_arr[0]) if len(onset_arr) else None
    first_det, Z = detect(DI, healthy, n_warm=warm)
    lat = (first_det - true_onset) if (first_det is not None and true_onset is not None) else None
    print(f'{month}: DI {DI.shape} ({time.time()-t0:.0f}s), true_onset={true_onset}, first_det={first_det}, latency={lat}')
    np.save(f'results/e4v2_DI_{month}.npy', DI)
    np.save(f'results/e4v2_tag_{month}.npy', d['damage'])
    json.dump({'month': month, 'true_onset': true_onset, 'first_det': first_det, 'latency': lat},
              open(f'results/e4v2_{month}.json', 'w'), indent=1)
    return DI, d


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else '2021_04')
