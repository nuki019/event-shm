"""E5 (real OGW, 40 kHz): directional dependence of damage event patterns.
Bin the 66 paths by propagation direction; test whether damage-induced
event activity varies with direction (anisotropy of CFRP layup).
"""
import sys, os, json
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSetZip
from src.methods.sod import sod_encode

PROC='data/processed'
POS = np.array([[150,150],[250,110],[350,150],[390,250],[350,350],[250,390],
                [150,350],[110,250],[250,250],[180,320],[320,320],[250,180]], float)

def run(dam='D24', delta=0.004):
    RH=np.load(f'{PROC}/R_udam_f40.npy'); RD=np.load(f'{PROC}/R_{dam}_f40.npy')
    ch=OGWSetZip('OGW_CFRP_Temperature_udam.zip').channels()
    ang=(np.degrees(np.arctan2(POS[ch[:,1],1]-POS[ch[:,0],1],
                              POS[ch[:,1],0]-POS[ch[:,0],0])))%180.0
    # event activity per path (damaged - healthy baseline)
    def act(R):
        a=np.zeros(R.shape[1])
        for m in range(R.shape[0]):
            for c in range(R.shape[1]):
                a[c]+=len(sod_encode(R[m,c],delta)[0])
        return a/max(a.sum(),1)
    aH=act(RH); aD=act(RD)
    excess=aD-aH
    nb=6; bins=np.digitize(ang,np.linspace(0,180,nb+1))-1
    raw=np.array([excess[bins==b].sum() for b in range(nb)])
    # use absolute directional activity (strength), normalized to sum 1
    strength=np.abs(raw); strength=strength/max(strength.sum(),1e-9)
    centers=(np.linspace(0,180,nb+1)[:-1]+np.linspace(0,180,nb+1)[1:])/2
    print(f'{dam}: directional |event-activity| (per 30-deg bin, sum=1):')
    for c,s2 in zip(centers,strength): print(f'  {c:.0f} deg: {s2:.3f}')
    cv=float(strength.std()/ (strength.mean()+1e-9))
    print(f'direction CV: {cv:.3f} (0=isotropic, larger=more directional)')
    json.dump({'dam':dam,'centers':centers.tolist(),'strength':strength.tolist(),'cv':float(cv)},
              open(f'results/e5_{dam}.json','w'),indent=1)

if __name__=='__main__':
    run(sys.argv[1] if len(sys.argv)>1 else 'D24')
