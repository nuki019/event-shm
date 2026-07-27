# Event-Based Guided Wave SHM

Send-on-delta (SoD) event-driven acquisition for guided wave structural health monitoring:
separating temperature drift from damage via temporal structure of event streams.

See `04_导波监测事件化.md` for the full research plan (in Chinese).

## Status
- [x] E0: data acquisition pipeline (GitHub Actions relay for figshare)
- [ ] E1: baseline reproduction (BSS/OBS + DI)
- [ ] E2: Layer-A eventization + ROC/Pareto
- [ ] E3: temperature–damage discrimination
- [ ] E4: long-term dataset (layer-B)
- [ ] E5: directional analysis
- [ ] E6: ablation
- [ ] Paper (XeTeX)

## Environment
```
conda env create -f environment.yml
```
