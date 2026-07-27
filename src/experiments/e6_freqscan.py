"""E6: frequency sweep — detection AUC vs excitation frequency (40..260 kHz).
For each freq: prep signals, OBS+BSS vs <=40C pool, per-record DI AUC.
Identifies the most damage-sensitive frequency (often higher for discs)."""
import sys, os, json, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSetZip
from src.methods.baseline_fast import stretch_batch
from scipy.signal import butter, filtfilt
from sklearn.metrics import roc_auc_score

_BA = butter(3, 20e3/5e6, btype='high')
def prep(x):
    y = filtfilt(_BA[0], _BA[1], x, axis=1).astype(np.float32)
    n = np.sqrt((y**2).sum(axis=1, keepdims=True)) + 1e-9
    return y/n

def di(x, Bp, alphas):
    best=np.inf; xx=max(float(np.dot(x,x)),1e-9)
    for a in alphas:
        S=stretch_batch(Bp,a); R=S-x[None,:]; e=np.einsum('ij,ij->i',R,R); m=float(e.min())
        if m<best: best=m
    return best/xx

def run(freqs=None, n_rec=20):
    if freqs is None: freqs=[40,120,260]
    ud=OGWSetZip('OGW_CFRP_Temperature_udam.zip'); dm=OGWSetZip('OGW_CFRP_Temperature_dam_D24.zip')
    Tud=ud.temperatures()
    pool=np.where(Tud<=40)[0][::12][:8]
    alphas=np.linspace(0.985,1.015,13)
    out={}
    for f in freqs:
        t0=time.time()
        Bpool=np.stack([prep(ud.signals(int(i),f)) for i in pool])
        labels=[]; di_l=[]
        for cond,s in ((0,ud),(1,dm)):
            for m in range(n_rec):
                x=prep(s.signals(m,f))
                d=np.array([di(x[c],Bpool[:,c,:],alphas) for c in range(66)])
                labels.append(cond); di_l.append(d.mean())
        auc=roc_auc_score(np.array(labels),np.array(di_l))
        out[f]=auc
        print(f'f={f} kHz: D04 AUC={auc:.3f} ({time.time()-t0:.0f}s)',flush=True)
    json.dump(out,open('results/e6_freqscan_D24.json','w'),indent=1)
    print('saved')

if __name__=='__main__':
    run()
