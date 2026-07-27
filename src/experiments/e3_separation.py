"""E3: temperature-damage discrimination from event structure, no explicit
temperature compensation. Two protocols:

A) Temperature extrapolation: baselines only from 20-40C, test 40-60C.
   Compare threshold-DI after OBS+BSS (classic) vs event-feature classifier.
B) Layer-B event streams: DI(k) SoD events; temperature drift produces
   coherent slow events on all paths, damage a localized sudden burst.

Synthetic validation first; same code runs on real OGW once extracted.
"""
import sys, os, json, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.synthetic import make_cycle, DAMAGE_POS, path_signal, FS, N_SAMPLES
from src.methods.baseline_fast import bss_search
from src.methods.damage_index import di_residual_energy
from src.methods.sod import sod_encode, sod_series
from src.methods.discriminator import (cross_path_coherence,
                                       path_localization_index, discriminate)
from sklearn.metrics import roc_auc_score
from sklearn.linear_model import LogisticRegression


# ---------- Protocol A: temperature extrapolation ----------

def protocol_a(freq=100, seed=0):
    print('--- Protocol A: temperature extrapolation ---')
    ud = make_cycle(n_temps=41, t_lo=20, t_hi=60, freqs=[freq], damaged=False, seed=seed+1)
    dm = make_cycle(n_temps=41, t_lo=20, t_hi=60, freqs=[freq], damaged=True, seed=seed+2)
    temps = ud['temps']
    n_paths = len(ud['paths'])
    # baselines: undamaged records at <= 40 C only
    in_range = np.where(temps <= 40.0)[0]
    B = np.transpose(np.stack([ud['signals'][(freq, ti)] for ti in in_range]), (1, 0, 2))
    alphas = np.linspace(0.99, 1.01, 31)

    labels, di_classic, feats = [], [], []
    for ti in range(len(temps)):
        T = temps[ti]
        for cond, X in ((0, ud['signals'][(freq, ti)]), (1, dm['signals'][(freq, ti)])):
            ev_counts = np.zeros(n_paths)
            for pi in range(n_paths):
                x = X[pi]
                _, _, _, r = bss_search(x, B[pi], alphas)
                labels_row = None
                di_classic.append(di_residual_energy(x, r))
                labels.append(cond)
                t, s, lv = sod_encode(r, delta=0.03)
                ev_counts[pi] = len(t)
            # event features per record
            coh = cross_path_coherence(ev_counts, thresh=5)
            loc = path_localization_index(ev_counts)
            feats.append([coh, loc, ev_counts.mean(), ev_counts.std()])
    labels = np.array(labels)
    feats = np.array(feats)
    rec_labels = np.tile([0, 1], len(temps) * 1)  # per record
    auc_classic = roc_auc_score(labels, di_classic)
    # simple supervised: logistic on features (train on records <40C, test >40C)
    rec_temps = np.repeat(temps, 2)
    tr = rec_temps <= 40
    te = rec_temps > 40
    clf = LogisticRegression(max_iter=1000).fit(feats[tr], rec_labels[tr])
    p = clf.predict_proba(feats[te])[:, 1]
    auc_feat = roc_auc_score(rec_labels[te], p)
    # classic DI at record level for same split (mean over paths)
    di_rec = np.array(di_classic).reshape(len(temps), 2, n_paths).mean(axis=2)
    auc_classic_ext = roc_auc_score(rec_labels[te], di_rec[te, 1] if False else di_rec[te].reshape(-1))
    print(f'  classic OBS+BSS DI, all temps AUC: {auc_classic:.3f}')
    print(f'  classic DI on extrapolated >40C records AUC: {auc_classic_ext:.3f}')
    print(f'  event-feature logistic on >40C records AUC: {auc_feat:.3f}')
    return {'auc_classic_all': auc_classic, 'auc_classic_extrap': auc_classic_ext,
            'auc_eventfeat_extrap': auc_feat}


# ---------- Protocol B: layer-B long-term ----------

def synth_longterm(n_days=900, freq=100, damage_day=450, seed=3):
    """One record per day; seasonal+daily temperature; damage onset mid-way."""
    from src.data.synthetic import RNG_POS
    rng = np.random.default_rng(seed)
    temps = 30 + 15 * np.sin(2 * np.pi * np.arange(n_days) / 365) + rng.normal(0, 2, n_days)
    paths = [(i, j) for i in range(12) for j in range(12) if i != j]
    pos = RNG_POS
    recs = np.empty((n_days, len(paths), N_SAMPLES))
    for d in range(n_days):
        damaged = d >= damage_day
        for pi, (i, j) in enumerate(paths):
            recs[d, pi] = path_signal(pos[i], pos[j], freq * 1e3, temps[d],
                                      damaged=damaged, rng=rng)
    return temps, recs, paths, pos


def protocol_b(n_days=900, damage_day=450, delta=0.02, seed=3):
    print('--- Protocol B: layer-B event streams ---')
    t0 = time.time()
    temps, recs, paths, pos = synth_longterm(n_days=n_days, damage_day=damage_day, seed=seed)
    n_paths = len(paths)
    # baselines: first 30 days
    B = recs[:30].mean(axis=0)
    alphas = np.linspace(0.99, 1.01, 21)
    dis = np.empty((n_days, n_paths))
    for d in range(n_days):
        for pi in range(n_paths):
            _, _, _, r = bss_search(recs[d, pi], B[None, pi, :] if B.ndim == 2 else B[pi], alphas)
            dis[d, pi] = di_residual_energy(recs[d, pi], r)
    print(f'  DI series computed in {time.time()-t0:.0f}s')
    # SoD on DI series per path
    delta_di = np.median(dis[:100]) * 0.5
    ev_t, ev_paths = [], []
    for pi in range(n_paths):
        t, s, lv = sod_series(dis[:, pi], delta_di)
        ev_t.extend(t.tolist())
        ev_paths.extend([pi] * len(t))
    ev_t = np.array(ev_t); ev_paths = np.array(ev_paths)
    print(f'  total layer-B events: {len(ev_t)} from {n_days} records '
          f'({n_days*n_paths} path-records) -> compression {n_days*n_paths/max(len(ev_t),1):.0f}x')
    # damage detection from events: for each day window, count events on
    # near-damage paths vs all
    def near(p, pos, D=DAMAGE_POS):
        a, s = pos[p[0]], pos[p[1]]
        ab = s - a
        u = np.clip(((D - a) @ ab) / (ab @ ab), 0, 1)
        return np.linalg.norm(D - (a + u * ab)) < 25
    near_mask = np.array([near(p, pos) for p in paths])
    win = 30
    days_axis = np.arange(0, n_days, win)
    near_frac = []
    for d0 in days_axis:
        m = (ev_t >= d0) & (ev_t < d0 + win)
        if m.sum() == 0:
            near_frac.append(0.0)
        else:
            near_frac.append(float(near_mask[ev_paths[m]].mean()))
    near_frac = np.array(near_frac)
    # detection: does near-fraction rise after damage onset?
    base = near_frac[days_axis < damage_day - win]
    test = near_frac[days_axis >= damage_day]
    print(f'  near-path event fraction: pre-damage {base.mean():.3f} vs post-damage {test.mean():.3f}')
    print(f'  near paths are {near_mask.mean()*100:.0f}% of all paths; lift = {test.mean()/max(base.mean(),1e-9):.2f}x')
    return {'n_events': int(len(ev_t)), 'pre': float(base.mean()), 'post': float(test.mean())}


if __name__ == '__main__':
    os.makedirs('results', exist_ok=True)
    out = {}
    out['A'] = protocol_a()
    out['B'] = protocol_b()
    json.dump(out, open('results/e3_synthetic.json', 'w'), indent=1)
    print('saved results/e3_synthetic.json')
