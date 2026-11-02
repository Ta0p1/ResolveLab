# Dialect transfer study — v0.5

Registered before any model episode in a held-out dialect
([protocol](../../docs/dialect-transfer-protocol.md), commit `3831439`); test inputs and all 18
adapters locked before the first test episode ([lock](test-lock.json), committed in `7252ddf`,
recording commit `d092177`). Same service, faults, records and grader as
[v0.4](../v0.4/RESULTS.md); only the tool contract changes ([API dialects](../../docs/dialects.md)).
Synthetic ticket service over real HTTP, local inference on one RTX 4060 Ti 8 GB.

**Zero-shot transfer (Q1, descriptive).** Adapters trained on one contract lose most of their skill
on a contract they have never seen: `bc` falls from 90.8% to 40.6% (does not transfer), `bc-volume`
from 90.8% to 53.6% and `dagger` from 98.3% to 61.7% (both partial).

**Contract diversity (Q2, primary).** Rendering the same 64 expert episodes in varied train dialects
raised the pass rate on held-out dialects from 40.6% to 53.9%: **+13.3 pp, 95% CI [1.1, 26.1]**
(training seeds × records), [8.1, 19.2] when resampling compositions. The registered rule classifies
this as **supported**, with fewer safety violations. It comes with a stated cost: on the original
study contract the same adapters fall from 90.8% to 55.6%.

**DAgger under diversity (Q3).** `dagger-multi` beat the size-matched `bc-volume-multi`, 81.4% vs
67.2%: **+14.2 pp, 95% CI [4.2, 23.9]**, [4.4, 23.9] when resampling compositions. The registered
verdict is **supported but fails safety non-inferiority**: 17.0 vs 14.0 episodes per 120 with a safety
violation, +3.0 against a limit of +2. `dagger-multi` keeps 95.0% on the study contract (98.3% for
`dagger`), within the 5 pp line for a stated cost.

`dagger-multi` is the best arm in held-out dialects, but it still fails 18.6% of episodes and writes
unsafely more often than its control.

## Test: 120 episodes, each in its own held-out dialect

These are the v0.4 test episodes. Every tool, argument, field, enum value and error is renamed from
a word pool disjoint from training; the concurrency token, pagination, status codes and time unit
change too. Pass = grader v2.

| Arm | Trained on | Per-seed passes /120 | Mean | Unsafe writes | False success | Spurious escalation | Found target |
|---|---|---|---:|---:|---:|---:|---:|
| `base-1.7b` | not trained | 20 | 16.7% | 46 | 95 | 8 | 64 |
| `bc` | study contract | 42, 49, 55 | 40.6% | 10, 19, 10 | 35, 55, 32 | 15, 9, 1 | 78, 85, 88 |
| `bc-volume` | study contract | 64, 76, 53 | 53.6% | 7, 1, 7 | 47, 21, 45 | 8, 2, 5 | 112, 115, 89 |
| `dagger` | study contract | 83, 61, 78 | 61.7% | 5, 6, 4 | 21, 47, 20 | 9, 14, 2 | 114, 100, 101 |
| `bc-multi` | train dialects | 57, 77, 60 | 53.9% | 5, 8, 4 | 39, 26, 36 | 5, 3, 1 | 110, 111, 114 |
| `bc-volume-multi` | train dialects | 87, 75, 80 | 67.2% | 1, 2, 1 | 15, 12, 7 | 5, 3, 0 | 119, 116, 119 |
| `dagger-multi` | train dialects | **105, 93, 95** | **81.4%** | 11, 11, 10 | 8, 16, 19 | 1, 3, 1 | 119, 111, 114 |

Seed order in this document is 3407, 42, 2026 (the generated `analysis-*.md` tables list seeds in
string order, 2026, 3407, 42). Per-seed Wilson intervals: `base-1.7b` [11.1, 24.3]; `bc` [27.1, 43.9],
[32.5, 49.8], [37.2, 54.7]; `bc-volume` [44.4, 62.0], [54.4, 71.4], [35.6, 53.1]; `dagger` [60.4, 76.7],
[42.0, 59.6], [56.1, 72.9]; `bc-multi` [38.8, 56.4], [55.3, 72.2], [41.2, 58.8]; `bc-volume-multi`
[63.9, 79.7], [53.6, 70.6], [57.8, 74.5]; `dagger-multi` [80.4, 92.3], [69.2, 84.1], [71.1, 85.5].
Schema-valid call rates were 99.5–100%. The v0.3 grader and grader v2 agree except on one episode
each for `bc` and `dagger` (both seed 42).

## Q1: zero-shot transfer

Paired against each adapter's own published v0.4 result on the same episodes in the study contract.
The registered classes: *transfers* (within 5 pp, with the interval's upper bound on the drop at most
10 pp), *does not transfer* (below 50% in dialects), otherwise *partial*.

| Adapter | Study contract | Held-out dialects | Δ (pp) | Paired 95% CI | Class | Gained–lost per seed |
|---|---:|---:|---:|---|---|---|
| `bc` | 90.8% | 40.6% | −50.3 | [−61.7, −37.5] | does not transfer | 1–72, 1–64, 5–52 |
| `bc-volume` | 90.8% | 53.6% | −37.2 | [−48.3, −25.8] | partial | 2–53, 4–36, 7–58 |
| `dagger` | 98.3% | 61.7% | −36.7 | [−47.5, −26.7] | partial | 1–36, 0–56, 0–41 |
| `base-1.7b` | 23.3% | 16.7% | −6.7 | [−15.8, 2.5] | does not transfer | one seed: 15–23 |

The protocol also asks whether the DAgger advantage survives a contract the adapters never saw.
`dagger − bc-volume` is +8.1 pp, about the v0.4 gap (+7.5), but the seeds × records interval includes
0 ([−6.7, 21.9]) and seed 42 reverses (wins–losses 24–5, 14–29, 32–7). The study does not establish
that it survives. `base-1.7b` is far below every trained arm, so the protocol's baseline-headline rule
does not apply.

## Paired comparisons (same 120 episodes, held-out dialects)

| Comparison | Δ (pp) | Seeds × records 95% CI | Composition-cluster 95% CI | Wins–losses per seed | Safety difference per 120 |
|---|---:|---|---|---|---:|
| **`bc-multi` − `bc`** (Q2) | **+13.3** | **[1.1, 26.1]** | [8.1, 19.2] | 29–14 (p=0.032), 35–7 (p<0.0001), 24–19 (p=0.54) | −12.7 |
| **`dagger-multi` − `bc-volume-multi`** (Q3) | **+14.2** | **[4.2, 23.9]** | [4.4, 23.9] | 27–9 (p=0.0039), 29–11 (p=0.0064), 26–11 (p=0.020) | **+3.0** |
| `dagger` − `bc-volume` | +8.1 | [−6.7, 21.9] | [0.8, 15.3] | 24–5, 14–29, 32–7 | −6.0 |
| `bc-volume-multi` − `bc-volume` | +13.6 | [0.8, 26.7] | [5.6, 21.7] | 30–7, 20–21, 38–11 | −26.0 |
| `dagger-multi` − `dagger` | +19.7 | [7.8, 32.2] | [7.8, 30.3] | 30–8, 44–12, 26–9 | −17.0 |
| `bc-multi` − `base-1.7b` | +37.2 | [25.0, 49.7] | [23.6, 52.0] | | −62.3 |

P values are exact McNemar. The intervals are the v0.4 ones: the seeds × records interval resamples each
arm's three training seeds and the episodes within composition strata (10,000 draws), and the
composition-cluster interval asks about other compositions like these. Q2's lower bound is close to 0
and one of its three seed pairs is not significant on its own. Raw numbers:
[analysis-test.json](analysis-test.json).

## Cost of diversity

The multi arms ran the same 120 episodes on the study contract. This reuses the public v0.4 test as a
measure of what diversity costs, never for selection. The protocol states any drop above 5 pp as a cost.

| Multi arm | Per-seed passes /120 | Mean | v0.4 counterpart | Δ (pp) | Stated as a cost |
|---|---|---:|---:|---:|---|
| `bc-multi` | 60, 86, 54 | 55.6% | `bc` 90.8% | −35.3 | **yes** |
| `bc-volume-multi` | 71, 55, 54 | 50.0% | `bc-volume` 90.8% | −40.8 | **yes** |
| `dagger-multi` | 116, 111, 115 | 95.0% | `dagger` 98.3% | −3.3 | no |

Schema-valid call rates here were 92.4–98.8% for `bc-multi`, 94.6–96.0% for `bc-volume-multi` and 100% for
`dagger-multi`; [failure causes](#failure-causes-exploratory) shows why.

## Safety: why Q3 fails non-inferiority

| Three seeds pooled | `bc-volume-multi` | `dagger-multi` |
|---|---:|---:|
| Episodes with an unsafe write | 4 | 13 |
| Episodes with false success | 34 | 43 |
| Episodes with a spurious escalation | 8 | 5 |
| **Episodes with any of these, per 120** | **14.0** | **17.0** |
| Episodes with a committed write | 91 | 156 |

The registered limit is +2 per 120; the difference is +3.0. `dagger-multi` reaches a write far more
often, because it does not die on the concurrency token. That exposure does not explain the whole gap:
per episode with a commit, unsafe writes are 8.3% vs 4.4% (small counts; not a registered comparison).
The 13 episodes are 7 distinct test episodes, two of which fail in all three seeds. 22 of the 32 unsafe
writes come from one episode (`test_rate_lost-02` in `heldout-95`), where the model wrote wrong values
and repeated them until the budget ran out. Against `dagger`, its zero-shot counterpart, `dagger-multi`
halves safety violations (34.0 to 17.0 per 120).

## Failure causes (exploratory)

Every failed episode was classified from its trace, three seeds pooled, one cause each
([diagnostics](diagnostics/failure-causes.md)). The taxonomy was written after the results were seen,
is not part of the registered analysis and changes no verdict.

| Cause | `bc` | `bc-volume` | `dagger` | `bc-multi` | `bc-volume-multi` | `dagger-multi` | | `bc-multi` | `bc-volume-multi` | `dagger-multi` |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|
| | held-out | held-out | held-out | held-out | held-out | held-out | | study | study | study |
| Token runs to output cap | 0 | 3 | 0 | 7 | 12 | 0 | | 102 | 132 | 0 |
| Malformed-token loop | 14 | 14 | 0 | 39 | 61 | 0 | | 15 | 34 | 0 |
| Other invalid output | 5 | 1 | 2 | 0 | 0 | 3 | | 0 | 0 | 0 |
| Repeated-write loop | 3 | 0 | 5 | 0 | 0 | 8 | | 0 | 0 | 1 |
| Other budget loop | 45 | 26 | 27 | 10 | 0 | 8 | | 2 | 0 | 0 |
| Wrong-record write | 34 | 15 | 14 | 15 | 4 | 5 | | 9 | 1 | 4 |
| Wrong-value write | 1 | 0 | 1 | 2 | 0 | 5 | | 3 | 1 | 2 |
| Claims success, no write attempted | 65 | 35 | 31 | 58 | 13 | 25 | | 11 | 5 | 9 |
| Claims success after a refused write | 21 | 55 | 31 | 26 | 17 | 7 | | 14 | 7 | 2 |
| Escalation error | 24 | 18 | 26 | 9 | 11 | 5 | | 0 | 0 | 0 |
| Other | 2 | 0 | 1 | 0 | 0 | 1 | | 4 | 0 | 0 |
| **Failures** | 214 | 167 | 138 | 166 | 118 | 67 | | 160 | 180 | 18 |

**The v0.4 mechanism carries across contracts.** v0.4 traced its result to one compounding error and
warned that the mechanism was specific to its contract. Here the same error appears across token styles:
the model mangles the concurrency token, is refused, re-reads and repeats, or keeps extending the token
until the 192-token output cap. It causes 73 of 118 `bc-volume-multi` failures in held-out dialects
and 166 of 180 on the study contract. No `dagger` or `dagger-multi` episode failed this way, in any
contract. DAgger rollouts reach that state: among kept labels where the teacher disagreed with the
learner, the write with a different token was 183 of 204 (seed 3407), 107 of 184 (seed 42) and 116 of
199 (seed 2026).

**Where the cost of diversity comes from.** The study contract's token is the quoted ETag `"v5"`. v0.4's
`bc` saw it in all 64 training episodes; `bc-multi` saw it in 17 of 64, among four token styles. The
held-out slices agree: on the quoted style `bc-multi` passes 31.0% and `bc-volume-multi` 47.6%, against
64.4% and 86.2% on integer revisions, while `dagger-multi` holds 76.2% and 82.8%. This is consistent with
the failure counts above, but no arm varied the token mix, so it is not an experimental finding.

**What remains for `dagger-multi`.** Its largest cause is reading the ticket and claiming success
without writing (25 of 67). In 24 of those 25, exactly one of the two requested fields already had its
requested value, which is true of 37.5% of all test episodes, so a partial match seems to be read as
done. Next come repeated writes after a commit (8), pagination loops (8) and success claims after a
refused write (7). Wrong-value writes (5) show a limit of constrained decoding: every value is valid in
the schema, and the model can still map a requested value to the wrong one. In `heldout-7`, for
example, it was asked for `on_hold` and wrote the value that means open.

## Pre-declared slices

Seed means, as diagnostics. They never replace the full denominator, and each slice is confounded with
the dialects that happen to fall in it.

| Slice (episodes) | `base-1.7b` | `bc` | `bc-volume` | `dagger` | `bc-multi` | `bc-volume-multi` | `dagger-multi` |
|---|---:|---:|---:|---:|---:|---:|---:|
| Token: quoted ETag (28) | 10.7% | 23.8% | 42.9% | 63.1% | 31.0% | 47.6% | 76.2% |
| Token: integer revision (29) | 34.5% | 47.1% | 67.8% | 59.8% | 64.4% | 86.2% | 82.8% |
| Token: weak ETag (37) | 8.1% | 45.0% | 48.6% | 61.3% | 56.8% | 53.2% | 82.0% |
| Token: version tag (26) | 15.4% | 44.9% | 56.4% | 62.8% | 62.8% | 87.2% | 84.6% |
| Pagination: `page-N` (23) | 21.7% | 60.9% | 66.7% | 71.0% | 65.2% | 72.5% | 89.9% |
| Pagination: opaque (28) | 17.9% | 46.4% | 54.8% | 59.5% | 64.3% | 76.2% | 88.1% |
| Pagination: offset (32) | 18.8% | 29.2% | 52.1% | 66.7% | 44.8% | 56.2% | 76.0% |
| Pagination: page number (37) | 10.8% | 33.3% | 45.9% | 53.2% | 46.8% | 66.7% | 75.7% |
| Wait unit: seconds (54) | 11.1% | 42.6% | 56.8% | 60.5% | 48.1% | 64.8% | 78.4% |
| Wait unit: milliseconds (66) | 21.2% | 38.9% | 51.0% | 62.6% | 58.6% | 69.2% | 83.8% |
| Conflict code: 409 (59) | 13.6% | 35.0% | 49.2% | 52.5% | 55.9% | 69.5% | 78.5% |
| Conflict code: 412 (61) | 19.7% | 45.9% | 57.9% | 70.5% | 51.9% | 65.0% | 84.2% |
| Seen wording (60) | 21.7% | 43.9% | 59.4% | 66.7% | 54.4% | 71.7% | 86.7% |
| Held-out wording (60) | 11.7% | 37.2% | 47.8% | 56.7% | 53.3% | 62.8% | 76.1% |
| `conflict_lost` (12) | 50.0% | 44.4% | 52.8% | 61.1% | 58.3% | 55.6% | 86.1% |
| `conflict_rate` (12) | 0.0% | 30.6% | 47.2% | 72.2% | 36.1% | 38.9% | 50.0% |
| `rate_lost` (12) | 0.0% | 22.2% | 25.0% | 41.7% | 36.1% | 41.7% | 69.4% |
| `conflict_rate_lost` (12) | 25.0% | 33.3% | 47.2% | 41.7% | 36.1% | 44.4% | 83.3% |
| `revoke_injection` (12) | 0.0% | 50.0% | 50.0% | 58.3% | 63.9% | 86.1% | 91.7% |
| `rate_revoke` (12) | 33.3% | 52.8% | 66.7% | 55.6% | 72.2% | 86.1% | 97.2% |
| `noop_injection` (12) | 8.3% | 77.8% | 91.7% | 91.7% | 91.7% | 100.0% | 97.2% |
| `concurrent_rate` (12) | 0.0% | 22.2% | 61.1% | 63.9% | 55.6% | 80.6% | 77.8% |
| `concurrent_injection` (12) | 25.0% | 44.4% | 55.6% | 63.9% | 44.4% | 86.1% | 77.8% |
| `lost_injection` (12) | 25.0% | 27.8% | 38.9% | 66.7% | 44.4% | 52.8% | 83.3% |

`dagger-multi`'s weakest composition is `conflict_rate` (18 of 36), which it passes 35 of 36 times on the
study contract.

## Dev (40 episodes in train dialects; a rehearsal only)

`base-1.7b` 8/40, `bc` 25/18/25, `bc-volume` 29/26/30, `dagger` 31/32/28, `bc-multi` 28/34/29,
`bc-volume-multi` 35/34/32, `dagger-multi` 40/39/40 (seeds 3407/42/2026). The multi arms trained in these
dialects on other episodes, so these numbers are not evidence about transfer. No arm, checkpoint or
setting was chosen on them, and the rehearsal exposed no plumbing defect.
[analysis-dev.json](analysis-dev.json).

## Data and training

| | `bc-multi` | `bc-volume-multi` | `dagger-multi` |
|---|---|---|---|
| Train rows | 396 expert (the 64 `train_core` episodes of `bc`) | 396 + 395 expert from `train_pool` | 396 + 395 DAgger rows from `train_pool` |
| Supervised tokens / epoch | 10,882 | 21,777 | 23,344 / 22,683 / 22,435 |
| Selected epoch (min dev loss) | 3, 3, 3 | 3, 3, 3 | 3, 3, 3 |
| Wall time (shared GPU) | 28–76 min | 76–90 min | 74–103 min |

Each row is in its episode's train dialect. The zero-shot arms are the published v0.4 adapters, pinned by
the v0.4 lock. DAgger, one iteration per seed: that seed's `bc-multi` adapter ran all 64 `train_pool`
episodes greedily and once with temperature 1.0 (same grammar). Greedy learners passed 50, 47 and 44 of 64;
sampled ones 47, 45 and 41. Every visited state was labelled by the teacher and kept only if the teacher's
continuation from it passed grader v2 (1,036, 913 and 907 labels; 5, 22 and 6 states dropped as
unrecoverable). The registered size match subsampled 395 of them uniformly. LoRA hyperparameters are the
v0.4 ones.

## Compute and deviations

Jobs ran for 21.2 hours with the host awake (dev 10.9, test 10.2), against a cap of 30. The clock count is
30.03 hours, because it includes 8.9 hours the host slept during the dev phase with every job paused. The
protocol's wording is "hours of wall-clock time with study jobs on the card", and this study reads it as
time they were running, so the cap was not reached. On the clock count it was passed by about two minutes,
during the last job: `bc-volume-multi` seed 2026 on the study contract, part of the first measurement the
protocol drops. That evaluation was kept. Dropping `bc-volume-multi`'s study-contract runs changes no
verdict, since Q1, Q2 and Q3 do not use them; with seed 2026 alone removed, the arm is still stated as a
cost (52.5%).

The test phase was interrupted once, at 102 of 120 episodes of that last job, when the session running it
ended. It resumed from its report; decoding is greedy and the environment deterministic. No source file,
benchmark, adapter or analysis changed after the lock. See [Deviations](../../docs/dialect-transfer-protocol.md#deviations).

## Limits

- Dialects share CaseDesk's records, faults and conventions. This measures transfer across contracts, not
  domains; token styles, pagination styles and codes occur in both splits, and only names are held out.
- Constrained decoding hands every arm the dialect's tool and argument names. Transfer here means mapping
  the right meaning onto them, not discovering them.
- One model family (0.6B trained), three training seeds, one DAgger iteration. Seeds disagree on the
  zero-shot DAgger comparison, and Q2's interval sits close to 0.
- The teacher is a hand-written runbook with exact knowledge of the contract; real agents rarely have a
  queryable expert.
- The arms are matched on rows, as registered, not on supervised tokens: `dagger-multi` carries 3–7% more
  target tokens per epoch than `bc-volume-multi`.
- The failure taxonomy and the explanations built on it are exploratory, written after the results.
- The host slept during the dev phase. Latency uses a monotonic clock that excludes it, and outcomes are
  unaffected.

## Verify without a GPU

```bash
python scripts/verify_dialect_transfer.py
```

It regenerates the expert data byte for byte, checks the locked source files, prompts, schemas, data and
adapter hashes, re-derives every DAgger label from the learner state stored in its row and re-verifies it
by teacher continuation, checks the dev reports against the lock, replays all 3,360 test episodes over real
HTTP in the contract each ran in (observations, verdicts and diagnostics must match), and recomputes the
registered analyses and the failure table. Traces are in `traces/` (one zip per arm), data in `data.zip`.
