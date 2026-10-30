# Dialect transfer study (v0.5) — draft protocol, not registered

**Status: draft for review. Nothing below has been run; no number here is a result.** It becomes
binding only when committed as registered with a date, before the first model episode in any
held-out dialect. Environment: [API dialects](dialects.md). Prior study: [v0.4 results](../artifacts/v0.4/RESULTS.md).

## Why

v0.4 found that verified DAgger labels beat the same number of extra expert rows (98.3% vs 90.8%), and
traced the gap to one mechanism: behaviour-cloned adapters mis-copy the quoted ETag and loop on 412. Its
limits section says the mechanism "is specific to this contract". Every v0.4 adapter was trained and
tested on one tool contract, so the study cannot tell recovery skill from memorised names. Dialects keep
the service, faults, records and grader and change only the contract.

## Questions

1. **Zero-shot transfer (descriptive).** On the 120 registered test episodes, each in a held-out dialect,
   how do the published v0.4 `bc`, `bc-volume` and `dagger` adapters and the `base-1.7b` baseline perform,
   paired against their own published results on the same episodes in the study contract? Does the
   DAgger advantage survive a contract the adapters have never seen?
2. **Contract diversity (primary).** Train on the **same** 64 `train_core` expert episodes as v0.4 `bc`,
   with each episode rendered in its own train-split dialect. Same states, same actions, same row count;
   only the contract surface differs. Does this beat v0.4 `bc` on held-out dialects?
3. **DAgger under diversity.** Repeat v0.4's size-matched comparison inside the multi-dialect regime:
   verified DAgger rows vs the same number of extra expert rows, both in train dialects.

## Dialect assignment (`benchmarks/casedesk-dialects-v1.json`, from `scripts/build_dialect_assignment.py`)

| Pool | Dialects | Use |
|---|---|---|
| `train_core`, `train_pool` | one `train` dialect per episode (128 distinct seeds) | training rows, DAgger rollouts |
| `dev` | one `train` dialect per episode, seeds disjoint from training (40) | checkpoint selection, smoke tests |
| `test` | one `heldout` dialect per episode (120 distinct seeds) | registered evaluation |

The file pins the generated dialects by hash; if this draft changes before registration, it is
regenerated under a new name. No model sees a held-out dialect before the test lock. Dev deliberately uses unseen *combinations* of
train words, not held-out words, so selection never touches the held-out vocabulary. Per-episode dialects
mean no single dialect's quirks dominate a pass rate.

## Arms

All arms: Qwen3, constrained decoding with the episode's dialect schema (`Translator.schema()`, LM Format
Enforcer, field order forced), 192 output tokens per action, 8192 context, 24 actions, greedy, the v0.4
one-shot demo translated into the dialect. Trained arms use the v0.4 LoRA hyperparameters and seeds (3407,
42, 2026) unchanged.

| Arm | Adapters | Training rows |
|---|---|---|
| `base-1.7b` | none | none |
| `bc` ×3 | published v0.4, unchanged | 396 expert, study contract |
| `bc-volume` ×3 | published v0.4, unchanged | 396 + 395 expert, study contract |
| `dagger` ×3 | published v0.4, unchanged | 396 + 395 DAgger, study contract |
| `bc-multi` ×3 | new | the same 396 expert states and actions, in train dialects |
| `bc-volume-multi` ×3 | new | + 395 expert rows from `train_pool`, in train dialects |
| `dagger-multi` ×3 | new | + 395 verified DAgger rows from `train_pool`, in train dialects |

DAgger in dialects: that seed's `bc-multi` adapter runs every `train_pool` episode in its train dialect,
greedy and sampled (T 1.0), as in v0.4. Each visited state is labelled by the teacher on the canonical
observations, rendered into the dialect, and kept only if the teacher's continuation from exactly that
state passes grader v2. The size match and subsample rule are v0.4's.

## Outcomes and analysis

- Primary: grader v2 pass on the 120 test episodes in held-out dialects. Secondary: every v0.4
  secondary outcome, plus the arm's pass rate on the study contract (the public v0.4 test, reused only as
  a measure of what diversity costs, never for selection).
- Pre-declared slices (diagnostics, never replacing the full denominator): token style, pagination
  style, time unit, whether 409 means conflict, composition, seen vs held-out phrasing.
- Paired differences on the same episodes: the v0.4 hierarchical bootstrap (training seeds × episodes
  within composition strata, 10,000 draws), the composition-cluster bootstrap, and exact McNemar per seed
  pair. For Q1, the pair is (dialect episode, canonical episode) for the same adapter.

## Decision rules (draft)

- **Q1** is descriptive. An arm *transfers* if its dialect pass rate is within 5 pp of its canonical rate
  and the interval's upper bound on the drop is ≤ 10 pp; *does not transfer* if its dialect pass rate is
  below 50%; otherwise *partial*.
- **Q2 supported** if `bc-multi − bc` ≥ +10 pp on held-out dialects and the hierarchical 95% interval
  excludes 0; **harmful** if the interval is entirely below 0; otherwise **inconclusive at this size**.
- **Q3 supported** if `dagger-multi − bc-volume-multi` ≥ +5 pp with the interval excluding 0; harmful and
  inconclusive as above; **uninformative (ceiling)** if both arms pass ≥ 95% in every seed.
- **Cost of diversity**: reported, not a gate. A multi arm more than 5 pp (seed mean) below its v0.4
  counterpart on the study contract is stated as a cost next to any Q2 or Q3 claim.
- Safety non-inferiority, as in v0.4: unsafe writes, false success and spurious escalations may not exceed
  the comparator's by more than 2 per 120 episodes (seed mean).
- If `base-1.7b` matches or beats the best trained arm on held-out dialects, that is the headline.

## Power

As in v0.4 (one seed pair, n = 120, simulated exact McNemar): +10 pp with 2% / 12% discordance is
detected with probability ≈ 0.83; +6 pp with 2% / 8% ≈ 0.46. Q2 is expected to be large or absent;
smaller effects will be reported as inconclusive, not absent.

## Before registration

Done (see [API dialects](dialects.md#study-plumbing)):

- the dialect-aware constrained policy (`dialects.policy.DialectPolicy`);
- expert and DAgger row builders whose messages and targets are dialect text, with the v0.4 provenance
  checks plus the assignment (`dialects.data`); the multi-dialect `train_core` rows are tested to be
  exactly v0.4's 396 `bc` states and actions;
- the assignment file and builder, dialect evaluation with per-episode convention columns, and the
  pipeline script `scripts/dialect_transfer.py`, which refuses the test pool;
- the lock (`scripts/lock_dialect_transfer.py`): assignment, study, v0.4 lock, every source file, the
  prompt and grammar of every test dialect, data, dev reports and all eighteen adapters (nine published
  v0.4, nine new). It refuses while this title says draft, with uncommitted changes, or once a test output
  exists. Its source hash ignores the `__version__` line from the start;
- the GPU-free audit (`scripts/verify_dialect_transfer.py`): it checks inputs against the lock,
  regenerates expert data, re-derives every DAgger label from the dialect conversation stored in its
  row, checks training reports against locked adapters, and replays every test episode in its dialect.

Still to do: the analysis script (Q1 pairs each dialect episode with the same adapter's published
canonical episode; Q2 and Q3 reuse the v0.4 hierarchical bootstrap and McNemar), written before the lock.

**Smoke test (2026-10-30, after the decision rules above were committed in `73377d9`).** The published
v0.4 `dagger` and `bc-volume` adapters (seed 42) ran the first 8 dev episodes, one composition, each in
its train-split dialect: 7/8 and 6/8 passed. This checks the plumbing and is not a result. The three
failures are model behaviour, not translation: a write to a near-miss record, a success claim without a
write, and the v0.4 token loop (`"v7","v6","v8"` growing until the JSON is cut off). Median latency was
13–15 s per episode.

**Compute (estimate from that latency).** Zero-shot evaluation ≈ 5 GPU-hours (nine adapters and
`base-1.7b`, 120 episodes each), training ≈ 11 (nine adapters, v0.4 wall times), DAgger rollouts and
labels ≈ 2, multi-arm evaluation in held-out dialects and the study contract ≈ 8: about 26 GPU-hours on
the RTX 4060 Ti. Proposed cap: 30. If exceeded, the study-contract evaluation of `bc-volume-multi` is
dropped first; registered held-out evaluations are not.

## Change control

As in v0.4: the lock records manifest, assignment, study config, source hashes, data hashes and every
selected adapter; nothing is tuned, re-trained, re-selected or dropped after it; a defect found later is
documented next to unchanged results. Existing v0.3 and v0.4 audits stay green: no locked file changes.

## Known limits of the design

- Dialects share CaseDesk's records, faults and conventions; this measures transfer across contracts, not
  domains. Conventions (token styles, pagination, codes, units) occur in both splits; only names are
  held out.
- Constrained decoding hands every arm the dialect's tool and argument names. Transfer here means mapping
  the right meaning onto them, not discovering them.
- One model family, 0.6B trained, three seeds, one DAgger iteration, a hand-written teacher.
