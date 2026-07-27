"""E2 (real OGW): detection AUC vs event rate (delta sweep), event vs
uniform decimation, on D04/D24 damage. Baseline pool <=40C from udam.
"""
import sys, os, json, time, argparse
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSetZip
from src.methods.baseline_fast import stretch_batch
from src.methods.sod import sod_encode, sod_decode
from sklearn.metrics import roc_auc_score


def residuals(x, Bpool, alphas):
    """Per-path OBS+BSS residual and norm."""
    K, C, N = Bpool.shape
    R = np.empty((C, N), dtype=np.float32)
    NN = np.empty(C)
    for c in range(C):
        best = np.inf; br = None
        for a in alphas:
            S = stretch_batch(Bpool[:, c, :], a)
            Rr = S - x[c][None, :]
            e = np.einsum('ij,ij->i', Rr, Rr)
            k = int(np.argmin(e))
            if e[k] < best: best = float(e[k]); br = Rr[k]
        R[c] = br
        NN[c] = max(float(np.dot(x[c], x[c])), 1e-9)
    return R, NN


def run(freq=100, dam='D04', n_rec=40, deltas=None):
    if deltas is None:
        deltas = np.geomspace(0.001, 0.05, 10)
    ud = OGWSetZip('OGW_CFRP_Temperature_udam.zip')
    Tud = ud.temperatures()
    pool_idx = np.where(Tud <= 40.0)[0][::8][:12]
    Bpool = np.stack([ud.signals(int(i), freq) for i in pool_idx])
    alphas = np.linspace(0.995, 1.005, 9)
    dm = OGWSetZip(f'OGW_CFRP_Temperature_dam_{dam}.zip')
    # collect residuals: healthy (udam, same temps) + damage
    t0 = time.time()
    RH = [residuals(ud.signals(m, freq), Bpool, alphas) for m in range(n_rec)]
    RD = [residuals(dm.signals(m, freq), Bpool, alphas) for m in range(min(n_rec, len(dm)))]
    print(f'residuals {len(RH)}+{len(RD)} ({time.time()-t0:.0f}s)', flush=True)
    rows = []
    for delta in deltas:
        labels, di_e, di_u, rates = [], [], [], []
        for cond, RR in ((0, RH), (1, RD)):
            for R, NN in RR:
                C, N = R.shape
                for c in range(C):
                    t, s, lv = sod_encode(R[c], delta)
                    rates.append(len(t) / N)
                    rec = sod_decode(t, lv, N)
                    labels.append(cond)
                    di_e.append(float(np.dot(rec, rec)) / NN[c])
                    rate = len(t) / N
                    step = max(1, int(round(1.0 / rate))) if rate > 1e-6 else N
                    uni = np.zeros(N, dtype=np.float32)
                    uni[::step] = R[c][::step]
                    di_u.append(float(np.dot(uni, uni)) / NN[c])
        labels = np.array(labels)
        ae = roc_auc_score(labels, di_e); au = roc_auc_score(labels, di_u)
        rows.append({'delta': float(delta), 'event_rate': float(np.mean(rates)),
                     'auc_event': float(ae), 'auc_uniform': float(au)})
        print(f'delta={delta:.3f} rate={rows[-1]["event_rate"]:.5f} AUC_ev={ae:.3f} AUC_uni={au:.3f}', flush=True)
    json.dump({'freq': freq, 'dam': dam, 'rows': rows},
              open(f'results/e2_real_f{freq}_{dam}.json', 'w'), indent=1)
    print('saved')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--freq', type=int, default=100)
    ap.add_argument('--dam', default='D04')
    ap.add_argument('--n-rec', type=int, default=40)
    args = ap.parse_args()
    run(args.freq, args.dam, args.n_rec)
