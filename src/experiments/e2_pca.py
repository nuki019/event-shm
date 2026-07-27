"""C3 (real, 40 kHz): SoD eventization vs PCA/SVD compression at equal rate.
Yang et al. 2023 style: project residual onto top-k principal components
of the baseline residuals; detection DI from PCA reconstruction vs events.
"""
import sys, os, json
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.methods.sod import sod_encode, sod_decode
from sklearn.metrics import roc_auc_score

PROC='data/processed'
import numpy as _np
_DGRID=_np.geomspace(1e-4,0.05,14)

def run(dam='D04', rates=None):
    RH=np.load(f'{PROC}/R_udam_f40.npy'); RD=np.load(f'{PROC}/R_{dam}_f40.npy')
    N=RH.shape[2]
    # PCA basis from healthy residuals (flatten paths*records)
    H=RH.reshape(-1,N)
    Hc=H-H.mean(0)
    U,S,Vt=np.linalg.svd(Hc,full_matrices=False)
    def full_di(RR): return (RR**2).sum(axis=2).mean(axis=1)
    labels=np.array([0]*RH.shape[0]+[1]*RD.shape[0])
    di_full=np.concatenate([full_di(RH),full_di(RD)])
    auc_full=roc_auc_score(labels,di_full)
    rows=[{'rate':1.0,'auc_event':float(auc_full),'auc_pca':float(auc_full)}]
    if rates is None: rates=[0.1,0.05,0.02,0.01,0.005,0.002,0.001]
    for rate in rates:
        # PCA: keep k components so k/N ~ rate
        k=max(1,int(rate*N))
        Vk=Vt[:k]
        di_p=[]; di_e=[]; er=[]
        for RR in [RH,RD]:
            for m in range(RR.shape[0]):
                dp=0; de=0; nev=0
                for c in range(0,RR.shape[1],3):
                    r=RR[m,c]
                    coeff=Vk@r
                    rec_p=coeff@Vk
                    dp+=float((rec_p**2).sum())
                    # event at matched rate: pick delta from a fixed grid
                    # that yields event count closest to target
                    tgt=int(rate*N)
                    chosen=None
                    for dd in _DGRID:
                        t,s,lv=sod_encode(r,dd)
                        if chosen is None or abs(len(t)-tgt)<chosen[0]:
                            chosen=(abs(len(t)-tgt),dd,t,s,lv)
                        if len(t)<=tgt:
                            break
                    _,bd,t,s,lv=chosen
                    rec=sod_decode(t,lv,N)
                    de+=float((rec**2).sum()); nev+=len(t)
                di_p.append(dp/(RR.shape[1]//3)); di_e.append(de/(RR.shape[1]//3)); er.append(nev/(N*(RR.shape[1]//3)))
        rows.append({'rate':float(np.mean(er)),
                     'auc_event':float(roc_auc_score(labels,di_e)),
                     'auc_pca':float(roc_auc_score(labels,di_p))})
        print(f'rate={rows[-1]["rate"]:.4f} AUC_event={rows[-1]["auc_event"]:.3f} AUC_pca={rows[-1]["auc_pca"]:.3f}',flush=True)
    json.dump({'dam':dam,'rows':rows},open(f'results/e2_pca_{dam}.json','w'),indent=1)
    print('saved')

if __name__=='__main__':
    run(sys.argv[1] if len(sys.argv)>1 else 'D04')
