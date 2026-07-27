"""E3-fidelity (real OGW): at equal data rate, how well does each scheme
preserve the damage-scattering structure? Metric: correlation between the
reconstructed residual envelope and the full-resolution residual envelope,
on damaged records, in the scattering time window.
"""
import sys, os, json
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.methods.sod import sod_encode, sod_decode
from scipy.signal import hilbert

PROC='data/processed'

def envelope(x):
    return np.abs(hilbert(x))

def run(dam='D24', deltas=None):
    if deltas is None: deltas=np.geomspace(0.0005,0.02,7)
    RD=np.load(f'{PROC}/R_{dam}_f100.npy')
    rows=[]
    for delta in deltas:
        cor_e, cor_u, rates = [], [], []
        for m in range(RD.shape[0]):
            for c in range(0, RD.shape[1], 6):
                r=RD[m,c]; N=len(r)
                env_full=envelope(r)
                # event reconstruction
                t,s,lv=sod_encode(r,delta)
                rec=sod_decode(t,lv,N)
                rates.append(len(t)/N)
                env_e=envelope(rec)
                # uniform decimation
                rate=len(t)/N
                step=max(1,int(round(1.0/rate))) if rate>1e-6 else N
                u=np.zeros(N); u[::step]=r[::step]
                env_u=envelope(u)
                # correlation in high-energy (scattering) region only
                thr=np.percentile(env_full,90)
                msk=env_full>thr
                if msk.sum()>10:
                    cor_e.append(np.corrcoef(env_full[msk],env_e[msk])[0,1])
                    cor_u.append(np.corrcoef(env_full[msk],env_u[msk])[0,1])
        rows.append({'delta':float(delta),'rate':float(np.mean(rates)),
                     'fidelity_event':float(np.nanmean(cor_e)),
                     'fidelity_uniform':float(np.nanmean(cor_u))})
        print(f'{dam} delta={delta:.4f} rate={rows[-1]["rate"]:.5f} fid_ev={rows[-1]["fidelity_event"]:.3f} fid_uni={rows[-1]["fidelity_uniform"]:.3f}',flush=True)
    json.dump({'dam':dam,'rows':rows},open(f'results/e2_fidelity_{dam}.json','w'),indent=1)
    print('saved')

if __name__=='__main__':
    run(sys.argv[1] if len(sys.argv)>1 else 'D24')
