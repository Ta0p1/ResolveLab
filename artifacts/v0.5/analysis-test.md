| Arm | Seeds | Pass rate mean (min–max) | Per-seed passes | Safety violations | Located target |
|---|---:|---|---|---:|---:|
| base-1.7b | 1 | 16.7% (16.7–16.7) | 20/120 | 99 | 64 |
| bc | 3 | 40.6% (35.0–45.8) | 55/120, 42/120, 49/120 | 148 | 88, 78, 85 |
| bc-multi | 3 | 53.9% (47.5–64.2) | 60/120, 57/120, 77/120 | 110 | 114, 110, 111 |
| bc-volume | 3 | 53.6% (44.2–63.3) | 53/120, 64/120, 76/120 | 120 | 89, 112, 115 |
| bc-volume-multi | 3 | 67.2% (62.5–72.5) | 80/120, 87/120, 75/120 | 42 | 119, 119, 116 |
| dagger | 3 | 61.7% (50.8–69.2) | 78/120, 83/120, 61/120 | 102 | 101, 114, 100 |
| dagger-multi | 3 | 81.4% (77.5–87.5) | 95/120, 105/120, 93/120 | 51 | 114, 119, 111 |

| Comparison | Δ pass rate (pp) | Seed×record 95% CI | Composition-cluster 95% CI |
|---|---:|---|---|
| bc-multi - bc | 13.3 | [1.1, 26.1] | [8.1, 19.2] |
| dagger-multi - bc-volume-multi | 14.2 | [4.2, 23.9] | [4.4, 23.9] |
| dagger - bc-volume | 8.1 | [-6.7, 21.9] | [0.8, 15.3] |
| bc-volume-multi - bc-volume | 13.6 | [0.8, 26.7] | [5.6, 21.7] |
| dagger-multi - dagger | 19.7 | [7.8, 32.2] | [7.8, 30.3] |
| bc-multi - base-1.7b | 37.2 | [25.0, 49.7] | [23.6, 52.0] |

| Q1 adapter | Study contract | Held-out dialects | Δ (pp) | 95% CI | Classification |
|---|---:|---:|---:|---|---|
| bc | 90.8% | 40.6% | -50.3 | [-61.7, -37.5] | does not transfer |
| bc-volume | 90.8% | 53.6% | -37.2 | [-48.3, -25.8] | partial |
| dagger | 98.3% | 61.7% | -36.7 | [-47.5, -26.7] | partial |
| base-1.7b | 23.3% | 16.7% | -6.7 | [-15.8, 2.5] | does not transfer |

Q2 (registered rule): **supported**.
Q3 (registered rule): **supported but fails safety non-inferiority**.
