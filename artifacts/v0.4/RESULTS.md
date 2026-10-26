# CaseDesk v2 study — v0.4

Registered before any v2 model run ([protocol](../../docs/casedesk-v2-protocol.md), commit
`286b30d`); test inputs and all 12 adapters locked before the first test episode
([lock](test-lock.json), committed in `5fc0c21`). Synthetic ticket service over real HTTP,
local inference on one RTX 4060 Ti 8 GB. Motivation: the [v0.3 review](../../docs/v0.3-review.md).

Commit messages on this branch were edited once before its first push (a trailer line
removed; no file changed), so hashes recorded during the run are pre-edit. The lock's
`commit` field, `c2f75c6`, is today's `7ace095`: both have tree `18bf466`
(`git rev-parse 7ace095^{tree}`).

**Primary result.** Adding verified DAgger labels at the learner's own states beat adding the
same number of extra expert rows from the same episodes: **98.3% vs 90.8%** test success
(seed means), **+7.5 pp, 95% CI [1.9, 13.3]** (training seeds × records), [2.2, 13.9] when
resampling compositions. The registered rule classifies this as **supported**, with no safety
cost (6 vs 6 episodes with an unsafe write, false success or spurious escalation). Extra
expert data alone changed nothing (`bc-volume − bc` = 0.0 pp).

## Test: 120 independent episodes, 10 held-out compositions

Every episode has its own record; a quarter have the target in slot 0 and half use one of two
task wordings never seen in training. Pass = grader v2 (verified resolution with a fresh read,
or escalation after an observed denial).

| Arm | Model | Per-seed passes (Wilson 95%) | Mean | Unsafe writes | False success | Found target |
|---|---|---|---:|---:|---:|---:|
| `base-0.6b` | 0.6B | 0/120 [0.0, 3.1] | 0.0% | 0 | 8 | 2 |
| `base-0.6b-3demo` | 0.6B, 3 demos | 0/120 [0.0, 3.1] | 0.0% | 2 | 7 | 17 |
| `base-1.7b` | 1.7B | 28/120 [16.7, 31.7] | 23.3% | 24 | 75 | 74 |
| `base-1.7b-3demo` | 1.7B, 3 demos | 18/120 [9.7, 22.5] | 15.0% | 28 | 94 | 60 |
| `v03-lora` | 0.6B + v0.3 adapters | 42, 30, 34 /120 | 29.4% | 19, 19, 12 | 63, 75, 84 | 65, 63, 72 |
| `bc` | 0.6B + LoRA | 113, 112, 102 /120 | 90.8% | 1, 4, 5 | 4, 8, 8 | 118, 116, 114 |
| `bc-volume` | 0.6B + LoRA | 115, 108, 104 /120 | 90.8% | 1, 2, 1 | 1, 4, 1 | 119, 118, 118 |
| `dagger` | 0.6B + LoRA | 118, 117, 119 /120 | **98.3%** | 0, 1, 0 | 2, 3, 1 | 120, 119, 120 |

Seed order in this document is 3407, 42, 2026 (the generated `analysis-*.md` tables list seeds
in string order, 2026, 3407, 42). Per-seed Wilson intervals: `bc` [88.4, 97.1], [87.4, 96.6],
[77.5, 90.3]; `bc-volume` [90.6, 98.2], [83.3, 94.2], [79.4, 91.6]; `dagger` [94.1, 99.5],
[92.9, 99.1], [95.4, 99.9]. Valid-call rates were 100% except `bc` (2,823/2,830, 99.75%),
`bc-volume` (2,976/2,987, 99.63%) and `base-0.6b-3demo` (618/619): every invalid call is an
ETag string that ran on until the 192-token output cap, so the JSON never closed (see below).
These episodes count as failures. The v0.3 grader and grader v2 agree on every test episode of
every arm.

## Paired comparisons (same 120 episodes)

| Comparison | Δ (pp) | Seeds × records 95% CI | Composition-cluster 95% CI | Exact McNemar per seed (wins–losses, p) |
|---|---:|---|---|---|
| **dagger − bc-volume** (primary) | **+7.5** | **[1.9, 13.3]** | [2.2, 13.9] | 5–2 (p=0.45), 10–1 (p=0.012), 16–1 (p=0.0003) |
| dagger − bc | +7.5 | [2.2, 14.2] | [3.9, 11.1] | 6–1, 6–1, 17–0 |
| bc-volume − bc | 0.0 | [−7.8, 8.1] | [−6.4, 5.6] | |
| bc − v03-lora | +61.4 | [50.8, 71.1] | [55.3, 67.8] | |
| bc − base-0.6b | +90.8 | [84.2, 96.4] | [86.9, 94.7] | |
| bc − base-1.7b | +67.5 | [58.1, 76.4] | [52.8, 80.6] | |
| dagger − base-1.7b | +75.0 | [68.3, 81.7] | [61.1, 87.5] | |

The seed × record interval resamples each arm's three training seeds and, independently, the
episodes within composition strata (10,000 draws); it covers record and optimisation variation
for these ten compositions. The composition-cluster interval asks about other compositions
like these. Raw numbers: [analysis-test.json](analysis-test.json).

## Why DAgger helped: one compounding error

Every failed episode was classified from its trace (mutually exclusive, three seeds pooled):

| Arm | Failures | Malformed-ETag 412 loop | ETag runs to output cap | Wrong-ticket write | False success | Other |
|---|---:|---:|---:|---:|---:|---:|
| `bc` | 33 | 5 | 7 | 10 | 9 | 2 |
| `bc-volume` | 33 | 15 | 11 | 4 | 2 | 1 |
| `dagger` | 6 | 0 | 0 | 1 | 5 | 0 |

The dominant behaviour-cloning failure is one compounding error in two forms. Either the model
copies the ETag with a stray character (for example `"v6",`), receives 412, re-reads the ticket
and repeats the same malformed copy until the 24-action budget runs out; or it keeps extending
the ETag string (`"v4",v5",v6",…`) until the 192-token output cap. Together these are 26 of 33
`bc-volume` failures. Expert demonstrations never contain a self-inflicted 412, so behaviour
cloning has no example of leaving that state, and more expert data did not add one.

DAgger rollouts reach it. Of the learner actions the teacher disagreed with, malformed-ETag
writes were 95 of 123 (seed 3407), 26 of 38 (seed 42) and 197 of 209 (seed 2026); each was
labelled with the write using the ETag just read, and kept only after the teacher, continuing
from that exact state, passed the grader. No `dagger` episode failed on an ETag. The
improvement is concentrated in the 412-conflict compositions (seed means, `bc-volume` →
`dagger`): `conflict_rate` 75% → 100%, `conflict_rate_lost` 75% → 100%, `conflict_lost`
81% → 92%; compositions without a 412 were already near ceiling.

Per seed, the gain mostly tracks how many failures the matched `bc-volume` adapter left to
fix (5, 12 and 16 failures for seeds 3407, 42, 2026; wins–losses 5–2, 10–1, 16–1), not the
number of malformed-ETag correction rows that the uniform subsample happened to keep (40, 11
and 72).

## Coverage: the v0.3 adapters on independent records

The published v0.3 adapters fall from 66.7–100% on the v0.3 test to **25.0–35.0%** here, with
63–84 false success claims per seed. They pass 10.0% of slot-0 targets (v2 `bc`: 93.3%) and
16.7% of held-out wordings versus 42.2% of seen ones (`dagger`: 97.8% vs 98.9%). The
[counterfactual diagnostic](diagnostics/position-summary.md) shows why: with records fixed,
they solve 54/54 later-page targets under the published demo and 0/54 when the demo's target
is on page one; their lookup copies the demonstration's layout.

| Slice (seed means) | v03-lora | bc | bc-volume | dagger | base-1.7b |
|---|---:|---:|---:|---:|---:|
| Target in slot 0 (30 episodes) | 10.0% | 93.3% | 88.9% | 98.9% | 6.7% |
| Target in slot 1 (30) | 54.4% | 96.7% | 91.1% | 98.9% | 26.7% |
| Target on page 2+ (60) | 26.7% | 86.7% | 91.7% | 97.8% | 30.0% |
| Seen wording (60) | 42.2% | 91.1% | 90.0% | 98.9% | 23.3% |
| Held-out wording (60) | 16.7% | 90.6% | 91.7% | 97.8% | 23.3% |

## Baselines

The base models fail mostly before any fault: the 0.6B base found the target in 2 of 120
episodes. The 1.7B base found it in 74 but then made 24 unsafe writes and 75 false success
claims. A stronger in-context prompt — three verified training demonstrations covering slot 0,
slot 1, a later page, a 412 refresh and a 403 escalation, chosen by a fixed rule — **did not
help** (1.7B: 15.0% vs 23.3%). Qwen3-1.7B in thinking mode (≤512 reasoning tokens per action,
Qwen3's recommended sampling) passed 10/40 on dev, below the 50% bar fixed before its first
episode, so it was not run on test ([amendment 1](../../docs/casedesk-v2-protocol.md)). 36% of
its steps hit the 512-token cap; a larger budget could do better at several times the cost.
These are small-model, local baselines, not frontier agents.

## Dev (40 episodes, 4 compositions; used for checkpoint selection)

`base-0.6b` 0/40, `base-1.7b` 15/40, `base-1.7b-3demo` 11/40, `think512-1.7b` 10/40,
`v03-lora` 9/7/11, `bc` 40/39/33, `bc-volume` 40/35/36, `dagger` 39/40/40 (seeds 3407/42/2026).
Dev showed the same direction (+6.7 pp, CI [−0.8, 15.0], inconclusive at n = 40, as the power
analysis predicted). [analysis-dev.json](analysis-dev.json).

## Data and training

| | `bc` | `bc-volume` | `dagger` |
|---|---|---|---|
| Train rows | 396 expert (64 `train_core` episodes) | 396 + 395 expert from `train_pool` | 396 + 395 DAgger rows from `train_pool` |
| Supervised tokens / epoch | 10,612 | 21,205 | 22,282 / 21,439 / 23,025 |
| Selected epoch (min dev loss) | 3, 3, 3 | 3, 3, 2 | 2, 3, 3 |
| Wall time (shared GPU) | 39–54 min | 76–90 min | 83–99 min |

DAgger, one iteration per seed: that seed's `bc` adapter ran all 64 `train_pool` episodes
greedily and once with temperature 1.0 (same grammar). Greedy learners already passed 62, 63
and 57 of 64; sampled ones 51, 56 and 43. Every visited state was labelled by the teacher and
kept only if the teacher's continuation from it passed grader v2 (951, 827 and 1,065 labels;
0–6 states per seed dropped as unrecoverable). The registered size match subsampled 395 of
them uniformly. LoRA hyperparameters are the v0.3 ones (rank 8, alpha 16, AdamW 2e-4, three
epochs, minimum dev action loss).

## Limits

- Synthetic, process-local service with a known contract and known fault primitives.
  Held-out compositions, records and wordings are not new tools, domains or real incidents.
- The arms are matched on rows (and therefore optimizer steps), as registered, not on
  supervised tokens: DAgger rows carry 1–9% more target tokens per epoch, because corrected
  writes are longer than reads.
- One DAgger iteration, one learner per seed, three training seeds, one model family (0.6B).
  The mechanism (an ETag copy loop) is specific to this contract; it shows *why* learner-state
  labels help here, not that they help everywhere.
- The teacher is a hand-written runbook with exact knowledge of the contract; real agents
  rarely have a queryable expert.
- Baselines are local 0.6B–1.7B models with one-shot, three-demo and thinking prompts.
- The machine suspended for ≈8 hours during the test phase. Decoding is greedy and the
  environment deterministic, so outcomes are unaffected; per-episode latency uses a
  monotonic clock that excludes suspend time.

## Verify without a GPU

```bash
python scripts/verify_casedesk_v2.py
```

It regenerates the manifest and expert data byte-for-byte, checks the locked source files,
prompt, schema, data and adapter hashes, re-derives every DAgger label from the learner state
stored in its row and re-verifies it by teacher continuation, replays all 1,920 test episodes
over real HTTP (observations, verdicts and diagnostics must match) and recomputes the
registered analysis. Traces are in `traces/` (one zip per arm), data in `data.zip`.
