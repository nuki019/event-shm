"""E4-onset: damage-onset detection from level-B DI events across months.

For a damage-onset month (mass 2021_04, dent 2021_05, hole 2022_07):
compute DI(k) with temperature-matched OBS from a HEALTHY reference month,
then SoD-eventize. Detection = persistent DI elevation on a path subset.
Reports detection latency (records after true onset) and FAR (healthy-month
false events).
"""
import sys, os, json, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.longterm_loader import load_month, PATHS
from src.methods.sod import sod_series


def di_against_reference(target_month, ref_month, n_ref=120, temp_bin=2.0):
    """DI(k) for target month using healthy reference month baselines."""
    ref = load_month(ref_month)
    healthy_ref = np.where(ref['damage'] == 0)[0][:n_ref]
    Bref = ref['gw'][healthy_ref]                 # (K, 8, N)
    Tref = ref['temp'][healthy_ref]
    d = load_month(target_month)
    gw = d['gw']; temp = d['temp']; M = gw.shape[0]; P = gw.shape[1]
    DI = np.empty((M, P), dtype=np.float32)
    for m in range(M):
        cand = np.where(np.abs(Tref - temp[m]) <= temp_bin)[0]
        if len(cand) == 0:
            cand = np.arange(len(Tref))
        for p in range(P):
            x = gw[m, p]
            best = np.inf
            xx = max(float(np.dot(x, x)), 1e-9)
            for cb in range(0, len(cand), 20):
                ch = cand[cb:cb+20]
                R = Bref[ch, p] - x[None, :]
                e = np.einsum('ij,ij->i', R, R)
                k = float(e.min())
                if k < best: best = k
            DI[m, p] = best / xx
    return d, DI


def onset_detection(DI, damage_tag, warm=200):
    """Detect onset: first epoch where DI stays above healthy threshold."""
    M, P = DI.shape
    # per-path robust healthy threshold from early healthy records
    thr = np.array([np.median(DI[:warm, p]) + 5 * np.median(np.abs(DI[:warm, p] - np.median(DI[:warm, p])))
                    for p in range(P)])
    # smoothed DI (moving mean over 50 records)
    k = 50
    sm = np.apply_along_axis(lambda v: np.convolve(v, np.ones(k)/k, 'same'), 0, DI)
    above = sm > thr[None, :]
    n_paths_above = above.sum(axis=1)
    # detection: >=2 paths simultaneously above threshold
    det = np.where(n_paths_above >= 2)[0]
    true_onset = np.where(damage_tag > 0)[0]
    true_onset = int(true_onset[0]) if len(true_onset) else None
    first_det = int(det[0]) if len(det) else None
    latency = (first_det - true_onset) if (first_det is not None and true_onset is not None) else None
    return {'threshold_per_path': thr.tolist(), 'first_detection': first_det,
            'true_onset': true_onset, 'latency_records': latency,
            'max_paths_above': int(n_paths_above.max())}


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else '2021_04'
    ref = sys.argv[2] if len(sys.argv) > 2 else '2018_03'
    t0 = time.time()
    d, DI = di_against_reference(target, ref)
    print(f'{target} vs ref {ref}: DI {DI.shape} in {time.time()-t0:.0f}s; '
          f'damage tags {np.unique(d["damage"])}', flush=True)
    res = onset_detection(DI, d['damage'])
    print(json.dumps(res, indent=1))
    np.save(f'results/e4_DI_{target}.npy', DI)
    np.save(f'results/e4_damtag_{target}.npy', d['damage'])
    json.dump({'target': target, 'ref': ref, **res}, open(f'results/e4_onset_{target}.json', 'w'), indent=1)
    print('saved')
