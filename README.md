# Event-Based Guided Wave SHM

Send-on-delta (SoD) event-driven acquisition for guided wave structural
health monitoring: separating temperature drift from damage via the
temporal structure of event streams.

Paper (XeTeX): `paper/main.tex` → `paper/main.pdf` (10 pp, 7 figs, 1 table).
Research plan (Chinese): `04_导波监测事件化.md`.

## Headline results (real data)

| Result | Value |
|---|---|
| E1: temp-extrapolation residual inflation (OGW, healthy) | 7.0× (>40 °C) |
| E2: D04 detection AUC @ 5000× compression (40 kHz) | **1.000** (event) vs 0.991 (uniform) |
| E2b: scattering-envelope fidelity @ ~10⁻³ rate | **0.6** (event) vs **0.06** (uniform) |
| C3: eventization vs PCA @ rate 2×10⁻³ | **0.950** vs **0.825** |
| E3: event-structure temp/damage discrimination (CV AUC) | 0.814 |
| E4: long-term level-B, 2021-04 (FAR, latency) | 0.1%, 269 h |
| E5: directional event-activity CV | 0.69 |
| E6: 40 kHz detection (D04/D24); compensation none/OBS/OBS+BSS | 1.0/0.95; 0.58/0.84/1.0 |

## Datasets (CC BY 4.0)
- OGW#2 CFRP temperature (Moll et al. 2019): 53.6 GB udam + 26.8 GB×2 damage,
  fetched via a figshare→S3 relay (`src/data/s3_download.py`, proxy only for
  the 302 redirect; S3 bucket reachable directly).
- UF/Utah 4.5-year outdoor aluminum (Yang et al. 2025): selected months.

## Pipeline
```
src/methods/sod.py            # vectorized send-on-delta encode/decode
src/methods/baseline_fast.py  # vectorized OBS/BSS temperature compensation
src/methods/discriminator.py  # coherence/localization event-structure features
src/experiments/              # E1..E6 experiment scripts
src/data/                     # OGW zip loader, long-term loader, S3 downloader
```

## Environment
```
conda env create -f environment.yml   # name: shm, python 3.11
```
