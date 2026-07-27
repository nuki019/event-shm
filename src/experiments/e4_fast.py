"""E4 (fast): level-B eventization on long-term data using temperature-matched
OBS baseline (no BSS stretch) -> per-path DI(k) -> SoD events.
Damage onset => sudden persistent DI step on affected paths.
"""
import sys, os, json, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.longterm_loader import load_month, available_months, PATHS
from src.methods.damage_index import di_residual_energy
from src.methods.sod import sod_series


def obs_di_month(ym, n_base=120, temp_bin=1.0):
    """DI(k) per path using temperature-matched optimal baseline selection."""
    d = load_month(ym)
    gw = d['gw']; temp = d['temp']; M = gw.shape[0]; P = gw.shape[1]
    healthy = np.where(d['damage'] == 0)[0]
    base_idx = healthy[:n_base]
    Btemp = temp[base_idx]
    DI = np.empty((M, P), dtype=np.float32)
    for m in range(M):
        # candidate baselines within temp_bin of current temperature
        cand = base_idx[np.abs(Btemp - temp[m]) <= temp_bin]
        if len(cand) == 0:
            cand = base_idx
        for p in range(P):
            x = gw[m, p]
            best_e = np.inf; best = cand[0]
            for cb in range(0, len(cand), 20):
                chunk = cand[cb:cb+20]
                R = gw[chunk, p] - x[None, :]
                e = np.einsum('ij,ij->i', R, R)
                k = int(np.argmin(e))
                if e[k] < best_e:
                    best_e = float(e[k]); best = chunk[k]
            DI[m, p] = best_e / max(float(np.dot(x, x)), 1e-9)
    return d, DI


def detect_onset(DI, temp, warm=300):
    """Per-path SoD on DI; report events and their temperature correlation."""
    out = {}
    dT = np.abs(np.gradient(temp))
    for p in range(DI.shape[1]):
        med = np.median(DI[:warm, p])
        delta = 0.5 * (med + 1e-9)
        t, s, lv = sod_series(DI[:, p], delta)
        out[p] = {'n_events': int(len(t)), 't': t,
                  'mean_dT_at_events': float(dT[t].mean()) if len(t) else 0.0,
                  'path': PATHS[p]}
    return out, dT


if __name__ == '__main__':
    months = available_months()
    print('months:', months)
    ym = sys.argv[1] if len(sys.argv) > 1 else months[0]
    t0 = time.time()
    d, DI = obs_di_month(ym)
    print(f'{ym}: DI {DI.shape} in {time.time()-t0:.0f}s; temp {d["temp"].min():.1f}..{d["temp"].max():.1f}C')
    ev, dT = detect_onset(DI, d['temp'])
    tot = sum(e['n_events'] for e in ev.values())
    M = DI.shape[0]
    print(f'level-B events: {tot} ({M*8/max(tot,1):.0f}x compression)')
    for p, e in ev.items():
        print(f'  path {e["path"]}: {e["n_events"]} events, mean|dT|@events {e["mean_dT_at_events"]:.4f} vs global {dT.mean():.4f}')
    np.save(f'results/e4_DI_{ym}.npy', DI)
    np.save(f'results/e4_temp_{ym}.npy', d['temp'])
    json.dump({'month': ym, 'n_events': tot}, open(f'results/e4_{ym}.json', 'w'))
    print('saved')
