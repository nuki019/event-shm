"""E5: directional event-pattern analysis on the 66 OGW paths (CFRP).

Bins paths by propagation direction angle; tests whether damage-induced
event-cluster strength/arrival-time is direction-dependent and whether
direction information improves coarse localization.
Works on real OGW once extracted; synthetic smoke-test otherwise.
"""
import sys, os, json
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

def path_angles(positions, paths):
    """Angle (deg) of each path's propagation direction in [0,180)."""
    ang = []
    for (i, j) in paths:
        d = positions[j] - positions[i]
        a = np.degrees(np.arctan2(d[1], d[0])) % 180.0
        ang.append(a)
    return np.array(ang)

def bin_paths(angles, n_bins=6):
    edges = np.linspace(0, 180, n_bins + 1)
    return np.digitize(angles, edges) - 1

def directional_strength(event_counts_per_path, angles, n_bins=6):
    bins = bin_paths(angles, n_bins)
    out = np.zeros(n_bins)
    for b in range(n_bins):
        m = bins == b
        out[b] = event_counts_per_path[m].sum()
    return out / max(out.sum(), 1)

if __name__ == '__main__':
    # smoke test on synthetic layout
    from src.data.synthetic import RNG_POS
    paths = [(i, j) for i in range(12) for j in range(12) if i != j]
    ang = path_angles(RNG_POS, paths)
    ec = np.random.rand(len(paths)) * (ang < 45)   # pretend events favour <45deg
    s = directional_strength(ec, ang)
    print('directional strength per 30-deg bin:', np.round(s, 3))
    print('smoke test ok')
