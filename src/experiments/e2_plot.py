"""Plot E2 Pareto results (synthetic or real)."""
import sys, os, json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def plot_pareto(path, out):
    d = json.load(open(path))
    rows = d['rows']
    rate = [r['event_rate'] for r in rows]
    auc_e = [r['auc_event'] for r in rows]
    auc_u = [r['auc_uniform'] for r in rows]
    plt.figure(figsize=(5, 4))
    plt.semilogx(rate, auc_e, 'o-', label='SoD events (ours)')
    plt.semilogx(rate, auc_u, 's--', label='uniform decimation')
    plt.axhline(0.95, color='gray', ls=':', lw=1)
    plt.xlabel('data rate (events per raw sample)')
    plt.ylabel('detection AUC')
    plt.title('Eventization Pareto: AUC vs data rate')
    plt.legend(); plt.tight_layout()
    plt.savefig(out, dpi=160)
    print('saved', out)

if __name__ == '__main__':
    plot_pareto(sys.argv[1], sys.argv[2])
