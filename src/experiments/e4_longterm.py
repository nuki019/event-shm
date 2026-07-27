"""E4: level-B eventization on the long-term outdoor dataset.

Per path: DI(k) = normalized residual energy vs a baseline (mean of the
first N healthy records at matched temperature, or OBS). SoD on DI(k).
Temperature produces slow coherent events on all paths; damage onset
produces a sudden persistent step. Reports detection latency & FAR.
"""
import sys, os, json, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.longterm_loader import load_month, available_months, PATHS
from src.methods.baseline_fast import bss_search
from src.methods.damage_index import di_residual_energy
from src.methods.sod import sod_series


def di_series_for_month(ym, n_base=60, alpha_grid=None):
    d = load_month(ym)
    gw = d['gw']                     # (M, 8, N)
    M, P, N = gw.shape
    temp = d['temp']
    if alpha_grid is None:
        alpha_grid = np.linspace(0.995, 1.005, 11)
    # baseline: first n_base healthy records
    healthy = np.where(d['damage'] == 0)[0]
    base_idx = healthy[:n_base]
    B = np.transpose(gw[base_idx], (1, 0, 2))   # (P, K, N)
    DI = np.empty((M, P), dtype=np.float32)
    for m in range(M):
        for p in range(P):
            k, a, bs, r = bss_search(gw[m, p], B[p], alpha_grid)
            DI[m, p] = di_residual_energy(gw[m, p], r)
    return d, DI


def sod_events_di(DI, delta_rel=0.5):
    """SoD per path on DI series; threshold relative to early-healthy median."""
    events = {}
    for p in range(DI.shape[1]):
        med = np.median(DI[:200, p])
        delta = delta_rel * (med + 1e-9)
        t, s, lv = sod_series(DI[:, p], delta)
        events[p] = {'t': t, 's': s, 'lv': lv, 'delta': delta}
    return events


if __name__ == '__main__':
    months = available_months()
    print('months available:', months)
    if not months:
        sys.exit('no monthly files downloaded yet')
    ym = months[0]
    t0 = time.time()
    d, DI = di_series_for_month(ym)
    print(f'{ym}: DI series {DI.shape} in {time.time()-t0:.0f}s; '
          f'temp {d["temp"].min():.1f}..{d["temp"].max():.1f} C')
    ev = sod_events_di(DI)
    tot = sum(len(e['t']) for e in ev.values())
    M = DI.shape[0]
    print(f'level-B events: {tot} from {M}x8 path-records '
          f'({M*8/max(tot,1):.0f}x compression)')
    # temperature correlation: DI event rate vs |dT/dt|
    dT = np.abs(np.gradient(d['temp']))
    all_t = np.sort(np.concatenate([e['t'] for e in ev.values()]))
    if len(all_t):
        print(f'mean |dT/dt| at event epochs {dT[all_t].mean():.4f} vs global {dT.mean():.4f}')
    np.save(f'results/e4_DI_{ym}.npy', DI)
    json.dump({'month': ym, 'n_events': tot, 'compression': M*8/max(tot,1)},
              open(f'results/e4_{ym}.json', 'w'), indent=1)
    print('saved')
