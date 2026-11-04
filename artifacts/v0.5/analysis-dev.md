| Arm | Seeds | Pass rate mean (min–max) | Per-seed passes | Safety violations | Located target |
|---|---:|---|---|---:|---:|
| base-1.7b | 1 | 20.0% (20.0–20.0) | 8/40 | 27 | 19 |
| bc | 3 | 56.7% (45.0–62.5) | 25/40, 25/40, 18/40 | 25 | 35, 35, 33 |
| bc-multi | 3 | 75.8% (70.0–85.0) | 29/40, 28/40, 34/40 | 11 | 37, 37, 37 |
| bc-volume | 3 | 70.8% (65.0–75.0) | 30/40, 29/40, 26/40 | 18 | 37, 35, 38 |
| bc-volume-multi | 3 | 84.2% (80.0–87.5) | 32/40, 35/40, 34/40 | 2 | 40, 40, 39 |
| dagger | 3 | 75.8% (70.0–80.0) | 28/40, 31/40, 32/40 | 10 | 36, 37, 36 |
| dagger-multi | 3 | 99.2% (97.5–100.0) | 40/40, 40/40, 39/40 | 0 | 40, 40, 40 |

| Comparison | Δ pass rate (pp) | Seed×record 95% CI | Composition-cluster 95% CI |
|---|---:|---|---|
| bc-multi - bc | 19.2 | [2.5, 37.5] | [3.3, 35.8] |
| dagger-multi - bc-volume-multi | 15.0 | [4.2, 25.8] | [1.7, 28.3] |
| dagger - bc-volume | 5.0 | [-10.8, 20.0] | [-9.2, 13.3] |
| bc-volume-multi - bc-volume | 13.3 | [-1.7, 28.3] | [0.0, 35.0] |
| dagger-multi - dagger | 23.3 | [12.5, 35.8] | [17.5, 32.5] |
| bc-multi - base-1.7b | 55.8 | [40.0, 71.7] | [45.8, 63.3] |

| Q1 adapter | Study contract | Held-out dialects | Δ (pp) | 95% CI | Classification |
|---|---:|---:|---:|---|---|
| bc | 93.3% | 56.7% | -36.7 | [-55.0, -17.5] | partial |
| bc-volume | 92.5% | 70.8% | -21.7 | [-35.8, -9.2] | partial |
| dagger | 99.2% | 75.8% | -23.3 | [-35.8, -12.5] | partial |
| base-1.7b | 37.5% | 20.0% | -17.5 | [-35.0, 0.0] | does not transfer |

Q2 (registered rule): **supported**.
Q3 (registered rule): **supported**.
