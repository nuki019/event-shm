"""E2: Layer-A eventization — ROC/AUC vs event rate (delta sweep).

Works on synthetic or real OGW data (via --source). For each delta:
  1. compensate residual (OBS+BSS or none)
  2. SoD-encode residual at threshold delta
  3. reconstruct zero-order-hold signal from events
  4. DI from reconstructed residual -> ROC vs true labels
  5. record event rate (events/sample) and equivalent bitrate

Also compares against uniform downsampling at the same data rate
(the C3 "post-hoc compression" confrontation).
"""
import sys, os, json, time, argparse
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.methods.baseline_fast import bss_search
from src.methods.damage_index import di_residual_energy
from src.methods.sod import sod_encode, sod_decode
from sklearn.metrics import roc_auc_score


def build_data_synthetic(freq=100, n_temps=21, seed_u=1, seed_d=2):
    from src.data.synthetic import make_cycle
    ud = make_cycle(n_temps=n_temps, t_lo=20, t_hi=60, freqs=[freq], damaged=False, seed=seed_u)
    dm = make_cycle(n_temps=n_temps, t_lo=20, t_hi=60, freqs=[freq], damaged=True, seed=seed_d)
    return ud, dm


def run_pareto(ud, dm, freq, deltas, alphas, compensate=True, max_paths=None):
    n_t = len(ud['temps'])
    n_paths = len(ud['paths'])
    if max_paths:
        n_paths = min(n_paths, max_paths)
    n_samp = ud['signals'][(freq, 0)].shape[1]
    B = np.transpose(np.stack([ud['signals'][(freq, ti)] for ti in range(n_t)]), (1, 0, 2))  # (P,K,N)

    # precompute residuals at all temps (shared across deltas)
    res_u, res_d, xnorm_u, xnorm_d = [], [], [], []
    t1 = time.time()
    for ti in range(n_t):
        for cond, X, acc, xn in ((0, ud['signals'][(freq, ti)], res_u, xnorm_u),
                                 (1, dm['signals'][(freq, ti)], res_d, xnorm_d)):
            rr = np.empty((n_paths, n_samp))
            nn = np.empty(n_paths)
            for pi in range(n_paths):
                if compensate:
                    _, _, _, r = bss_search(X[pi], B[pi], alphas)
                else:
                    r = X[pi] - B[pi, 0]
                rr[pi] = r
                nn[pi] = float(np.dot(X[pi], X[pi])) or 1.0
            acc.append(rr); xn.append(nn)
    print(f'residuals precomputed in {time.time()-t1:.1f}s')

    rows = []
    for delta in deltas:
        labels, di_ev, di_uni, rates = [], [], [], []
        for cond, res, xn in ((0, res_u, xnorm_u), (1, res_d, xnorm_d)):
            for rr, nn in zip(res, xn):
                for pi in range(n_paths):
                    t, s, lv = sod_encode(rr[pi], delta)
                    rates.append(len(t) / n_samp)
                    rec = sod_decode(t, lv, n_samp)
                    labels.append(cond)
                    # DI = energy of the *reconstructed* residual, normalized
                    di_ev.append(float(np.dot(rec, rec)) / nn[pi])
                    # uniform downsample comparison at matched rate
                    step = max(1, int(round(1.0 / max(len(t) / n_samp, 1e-9))))
                    uni = np.repeat(rr[pi][::step], step)[:n_samp]
                    if len(uni) < n_samp:
                        uni = np.pad(uni, (0, n_samp - len(uni)), mode='edge')
                    di_uni.append(float(np.dot(uni, uni)) / nn[pi])
        labels = np.array(labels)
        auc_ev = roc_auc_score(labels, di_ev)
        auc_uni = roc_auc_score(labels, di_uni)
        row = {'delta': float(delta), 'event_rate': float(np.mean(rates)),
               'auc_event': float(auc_ev), 'auc_uniform': float(auc_uni)}
        rows.append(row)
        print(f'delta={delta:.4f} rate={row["event_rate"]:.5f} '
              f'AUC_event={auc_ev:.3f} AUC_uniform={auc_uni:.3f}', flush=True)
    return rows


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', default='synthetic')
    ap.add_argument('--freq', type=int, default=100)
    ap.add_argument('--max-paths', type=int, default=40)
    ap.add_argument('--no-comp', action='store_true')
    ap.add_argument('--out', default='results/e2_pareto_synthetic.json')
    args = ap.parse_args()

    if args.source == 'synthetic':
        ud, dm = build_data_synthetic(freq=args.freq)
    else:
        raise NotImplementedError('real loader wiring comes after extraction')

    deltas = np.geomspace(0.01, 0.5, 10)
    alphas = np.linspace(0.995, 1.005, 21)
    rows = run_pareto(ud, dm, args.freq, deltas, alphas,
                      compensate=not args.no_comp, max_paths=args.max_paths)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump({'args': vars(args), 'rows': rows}, open(args.out, 'w'), indent=1)
    print('saved', args.out)
