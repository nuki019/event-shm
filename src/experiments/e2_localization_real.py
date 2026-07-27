"""E2-loc (real OGW): eventization vs uniform decimation for damage LOCALIZATION.

Damage position known for D04/D24 (collinear disc positions). From the
compensated residual, SoD-eventize at rate r; estimate the damage position
from per-path event activity + geometry. Compare localization error against
matched-rate uniform decimation. This is where eventization should win.
"""
import sys, os, json, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSetZip
from src.methods.sod import sod_encode

# OGW transducer positions (mm) on 500x500 plate, 12 DuraAct, from dataset docs
# approximate ring + inner layout used by OGW platform
POS = np.array([
    [150,150],[250,110],[350,150],[390,250],[350,350],[250,390],
    [150,350],[110,250],[250,250],[180,320],[320,320],[250,180]], dtype=float)
# damage nominal positions (collinear); distances from plate centre along one axis
DAM_XY = {'D04': np.array([250+40, 250.0]), 'D12': np.array([250+120, 250.0]),
          'D16': np.array([250+160, 250.0]), 'D24': np.array([250+240, 250.0])}

PROC='data/processed'
_CH = None
def channels():
    global _CH
    if _CH is None:
        _CH = OGWSetZip('OGW_CFRP_Temperature_udam.zip').channels()
    return _CH

def localize_event(R, delta, top_k=12):
    """R (M,66,N) residuals of damaged records. Average |events| per path
    across records, weight path midpoints -> position estimate."""
    P = R.shape[1]; N = R.shape[2]
    act = np.zeros(P)
    first = np.full(P, np.inf)
    for m in range(R.shape[0]):
        for c in range(P):
            t,s,lv = sod_encode(R[m,c], delta)
            act[c] += len(t)
            if len(t): first[c]=min(first[c],t[0])
    ch = channels()
    mids = (POS[ch[:,0]]+POS[ch[:,1]])/2
    top = np.argsort(act)[::-1][:top_k]
    w = act[top]+1e-9
    est = (mids[top]*w[:,None]).sum(0)/w.sum()
    return est, act.sum()/ (R.shape[0]*P*N)

def localize_uniform(R, step, top_k=12):
    P=R.shape[1]; N=R.shape[2]
    act=np.zeros(P)
    for m in range(R.shape[0]):
        for c in range(P):
            u=np.zeros(N); u[::step]=R[m,c][::step]
            act[c]+=np.abs(u).sum()
    ch = channels()
    mids=(POS[ch[:,0]]+POS[ch[:,1]])/2
    top=np.argsort(act)[::-1][:top_k]
    w=act[top]+1e-9
    return (mids[top]*w[:,None]).sum(0)/w.sum()

def run(dam='D24', deltas=None):
    if deltas is None: deltas=np.geomspace(0.0005,0.03,8)
    RD=np.load(f'{PROC}/R_{dam}_f100.npy')
    true=DAM_XY[dam]
    rows=[]
    for delta in deltas:
        est_e,rate=localize_event(RD,delta)
        step=max(1,int(round(1.0/max(rate,1e-6))))
        est_u=localize_uniform(RD,step)
        ee=np.linalg.norm(est_e-true); eu=np.linalg.norm(est_u-true)
        rows.append({'delta':float(delta),'rate':float(rate),
                     'loc_err_event':float(ee),'loc_err_uniform':float(eu)})
        print(f'{dam} delta={delta:.4f} rate={rate:.5f} err_ev={ee:.1f}mm err_uni={eu:.1f}mm',flush=True)
    json.dump({'dam':dam,'rows':rows},open(f'results/e2_loc_{dam}.json','w'),indent=1)
    print('saved')

if __name__=='__main__':
    run(sys.argv[1] if len(sys.argv)>1 else 'D24')
