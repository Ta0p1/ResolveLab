# Failure causes (exploratory)

Every failed episode, three seeds pooled, one cause each. Written after the results were
seen; not part of the registered analysis. `scripts/summarize_dialect_failures.py`.

| Cause | `test/bc` | `test/bc-volume` | `test/dagger` | `test/bc-multi` | `test/bc-volume-multi` | `test/dagger-multi` | `study-contract/bc-multi` | `study-contract/bc-volume-multi` | `study-contract/dagger-multi` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| token runs to output cap | 0 | 3 | 0 | 7 | 12 | 0 | 102 | 132 | 0 |
| malformed-token loop | 14 | 14 | 0 | 39 | 61 | 0 | 15 | 34 | 0 |
| other invalid output | 5 | 1 | 2 | 0 | 0 | 3 | 0 | 0 | 0 |
| repeated-write loop | 3 | 0 | 5 | 0 | 0 | 8 | 0 | 0 | 1 |
| other budget loop | 45 | 26 | 27 | 10 | 0 | 8 | 2 | 0 | 0 |
| wrong-record write | 34 | 15 | 14 | 15 | 4 | 5 | 9 | 1 | 4 |
| wrong-value write | 1 | 0 | 1 | 2 | 0 | 5 | 3 | 1 | 2 |
| claims success, no write attempted | 65 | 35 | 31 | 58 | 13 | 25 | 11 | 5 | 9 |
| claims success after a refused write | 21 | 55 | 31 | 26 | 17 | 7 | 14 | 7 | 2 |
| escalation error | 24 | 18 | 26 | 9 | 11 | 5 | 0 | 0 | 0 |
| other | 2 | 0 | 1 | 0 | 0 | 1 | 4 | 0 | 0 |
| **Failures** | 214 | 167 | 138 | 166 | 118 | 67 | 160 | 180 | 18 |
| Episodes with a commit | 110 | 112 | 144 | 99 | 91 | 156 | 93 | 38 | 174 |
| Episodes with an unsafe write | 37 | 15 | 15 | 17 | 4 | 13 | 12 | 2 | 6 |
