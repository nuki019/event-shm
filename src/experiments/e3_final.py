"""E3 (final, real, 40 kHz): temperature-damage discrimination via event
structure, focused on the extrapolation regime where compensation fails.

Features per record (from event stream across 66 paths):
  coherence (frac paths active), localization, n_events, arrival_std.
Compare rule-based vs logistic; report AUC overall and on >40C records.
"""
import sys, os, json
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.methods.sod import sod_encode
from src.methods.discriminator import cross_path_coherence, path_localization_index
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_predict, StratifiedKFold
from sklearn.metrics import roc_auc_score

PROC='data/processed'

def feats(R, delta):
    C=R.shape[0]; N=R.shape[1]
    ev=np.zeros(C); first=np.full(C,np.nan)
    for c in range(C):
        t,s,lv=sod_encode(R[c],delta)
        ev[c]=len(t)
        if len(t): first[c]=t[0]
    act=~np.isnan(first)
    return [cross_path_coherence(ev,3), path_localization_index(ev),
            ev.sum(), np.nanstd(first) if act.sum()>2 else 0.0, act.mean()]

def run(delta=0.004):
    RH=np.load(f'{PROC}/R_udam_f40.npy'); RD=np.load(f'{PROC}/R_D24_f40.npy')
    TH=np.load(f'{PROC}/T_udam_f40.npy'); TD=np.load(f'{PROC}/T_D24_f40.npy')
    XH=np.array([feats(RH[m],delta) for m in range(RH.shape[0])])
    XD=np.array([feats(RD[m],delta) for m in range(RD.shape[0])])
    X=np.vstack([XH,XD]); y=np.array([0]*len(XH)+[1]*len(XD))
    T=np.concatenate([TH,TD])
    Xs=(X-X.mean(0))/(X.std(0)+1e-9)
    cv=StratifiedKFold(5,shuffle=True,random_state=0)
    p=cross_val_predict(LogisticRegression(max_iter=1000),Xs,y,cv=cv,method='predict_proba')[:,1]
    print(f'event-structure discrimination (all temps): CV AUC {roc_auc_score(y,p):.3f}')
    ext=T>40
    if ext.sum()>5 and len(np.unique(y[ext]))>1:
        print(f'  on >40C records only: AUC {roc_auc_score(y[ext],p[ext]):.3f}')
    for i,k in enumerate(['coherence','localization','n_events','arrival_std','frac_active']):
        for sgn in [1,-1]:
            a=roc_auc_score(y,sgn*X[:,i])
            if a>0.6: print(f'    {k}: AUC {a:.3f}')
    json.dump({'delta':delta,'auc_all':float(roc_auc_score(y,p))},open('results/e3_final.json','w'))

if __name__=='__main__':
    run()
