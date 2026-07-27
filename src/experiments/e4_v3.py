"""E4 v3 (long-term, level-A->B): per-record within-record SoD event COUNT
as the damage index, then level-B SoD on that count series.

Rationale: raw residual energy DI drifts with temperature; the *count* of
level-crossing events of the compensated residual is far less sensitive to
slow amplitude drift (drift moves the mean, not the high-freq scatter).
Damage adds a persistent high-frequency scattering packet -> persistent
event-count elevation on affected paths.
"""
import sys, os, json, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.longterm_loader import load_month, PATHS
from src.methods.baseline_fast import stretch_batch
from src.methods.sod import sod_encode


def event_counts_month(month, n_base=120, temp_bin=2.0, delta=0.05, alpha_grid=None):
    if alpha_grid is None:
        alpha_grid = np.linspace(0.99, 1.01, 9)
    d = load_month(month)
    gw, temp, tag = d['gw'], d['temp'], d['damage']
    M, P, N = gw.shape
    healthy = np.where(tag == 0)[0]
    base = healthy[:n_base]
    BT = temp[base]
    EC = np.zeros((M, P), dtype=np.float32)
    for m in range(M):
        cand = base[np.abs(BT - temp[m]) <= temp_bin]
        if len(cand) == 0: cand = base
        for p in range(P):
            x = gw[m, p]
            # OBS (temperature-matched, no stretch) for speed
            best = np.inf; br = None
            for cb in range(0, len(cand), 15):
                ch = cand[cb:cb+15]
                R = gw[ch, p] - x[None, :]
                e = np.einsum('ij,ij->i', R, R)
                k = int(np.argmin(e))
                if e[k] < best: best = float(e[k]); br = R[k]
            t, s, lv = sod_encode(br, delta)
            EC[m, p] = len(t)
    return d, EC


def detect_onset(EC, tag, warm=300, z=4.0, K=2, win=100):
    M, P = EC.shape
    mu, sd = EC[:warm].mean(0), EC[:warm].std(0) + 1e-9
    Z = (EC - mu) / sd
    n_above = (Z > z).sum(1)
    det = np.zeros(M, bool)
    for m in range(M):
        a = max(0, m - win)
        det[m] = (n_above[a:m+1] >= K).mean() > 0.5
    idx = np.where(det)[0]
    onset_arr = np.where(tag > 0)[0]
    true_onset = int(onset_arr[0]) if len(onset_arr) else None
    first_det = int(idx[0]) if len(idx) else None
    lat = (first_det - true_onset) if (first_det is not None and true_onset is not None) else None
    return true_onset, first_det, lat, Z


if __name__ == '__main__':
    month = sys.argv[1] if len(sys.argv) > 1 else '2021_04'
    t0 = time.time()
    d, EC = event_counts_month(month)
    print(f'{month}: EC {EC.shape} ({time.time()-t0:.0f}s)', flush=True)
    to, fd, lat, Z = detect_onset(EC, d['damage'])
    print(f'true_onset={to}, first_det={fd}, latency={lat}')
    np.save(f'results/e4v3_EC_{month}.npy', EC)
    np.save(f'results/e4v3_tag_{month}.npy', d['damage'])
    json.dump({'month': month, 'true_onset': to, 'first_det': fd, 'latency': lat},
              open(f'results/e4v3_{month}.json', 'w'), indent=1)
