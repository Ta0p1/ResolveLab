# Study history

Every study keeps its own registered protocol, results and replayable evidence. Later
studies never edit earlier ones; when a later study found a problem with an earlier result,
the problem is documented next to it. The current study is v0.4.

| Study | Question | Headline | Status | Evidence |
|---|---|---|---|---|
| **v0.5** (draft) | Does what a model learned on one tool contract transfer to unseen API dialects, and does training on many dialects help? | None: not run | Draft protocol, not registered; environment and tooling on main | [protocol](dialect-transfer-protocol.md) · [dialects](dialects.md) |
| **v0.4** (2026-10) | Do learner-state (DAgger) labels beat the same amount of extra expert data? | DAgger 98.3% vs 90.8% on 120 independent episodes, +7.5 pp, CI [1.9, 13.3] | Current | [results](../artifacts/v0.4/RESULTS.md) · [protocol](casedesk-v2-protocol.md) · `scripts/verify_casedesk_v2.py` |
| **v0.3** (2026-10) | Does LoRA help a 0.6B model on a second (HTTP) contract with format controlled? | 0/30 → 20–30/30 across three seeds | **Superseded**: three effective test records; the adapters copied the demo's layout ([review](v0.3-review.md)) | [results](../artifacts/v0.3/RESULTS.md) · [protocol](httpdesk-protocol.md) · `scripts/verify_http_study.py` |
| **v0.2** (2026-10) | First local SFT on the SQLite sync service | 24/24 adapted vs base failures dominated by output-format errors | Historical; format confound disclosed | [results](../artifacts/v0.2/RESULTS.md) · [protocol](post-training.md) · `scripts/verify_experiment.py` |
| **v0.1** (2026-10) | Can a local 4B model recover ten synthetic sync faults? | 9/10 development scenarios (single seed) | Historical baseline | [results](../artifacts/RESULTS.md) |

## v0.3: control JSON structure, then measure outcomes

> Superseded as a headline by the [v0.3 self-review](v0.3-review.md); kept unchanged as the
> registered record.

- **Stronger baselines:** Qwen3-0.6B and Qwen3-1.7B use full tool-schema constrained
  decoding and one verified training demonstration. The LoRA arms use the identical
  prompt, schema and action/token budgets. No model-output repair or rule fallback.
  A separately labeled Qwen3-4B Q4_K_M / Ollama control checks a larger local model.
- **A second API contract:** paginated ticket lookup, exact reference matching,
  If-Match concurrency, idempotency keys, post-commit 502, Retry-After and mid-task
  permission revocation. Calls cross actual TCP sockets through httpx and FastAPI.
- **Repeated local training:** three registered LoRA seeds, 322 verified expert
  actions from 48 training episodes, development-loss checkpoint selection.
- **Fresh test:** 30 new episodes across 10 compositions and 3 disjoint record seeds,
  frozen before model runs. Valid-call rate, task success, unsafe writes, false success and
  unnecessary writes are separate measurements. All failures and all training seeds remain
  visible.
- **Executable evidence:** inspect every model episode in the workbench's **HTTP study**
  page, or replay the published actions with `python scripts/verify_http_study.py` (no GPU).

| Policy | Task success | Schema-valid calls | False success |
|---|---:|---:|---:|
| Qwen3-0.6B base | 0/30 | 100.0% | 10 |
| Qwen3-1.7B base | 12/30 | 100.0% | 14 |
| 0.6B LoRA / 3407 | 20/30 | 100.0% | 0 |
| 0.6B LoRA / 42 | 30/30 | 100.0% | 0 |
| 0.6B LoRA / 2026 | 20/30 | 100.0% | 10 |

Supplementary Qwen3-4B Q4_K_M / Ollama: 6/30 passed, 100.0% schema-valid calls; different
quantization and backend, not a matched training effect. [Release
validation](../artifacts/v0.3/validation.json): 129 tests, all 180 HTTP episode replays,
browser checks and a clean wheel installation passed. The HTTP backend is synthetic and
process-local; see the [model card](httpdesk-model-card.md) and
[architecture](architecture.md). The v0.3 publishing scripts (`scripts/write_http_results.py`,
`freeze_http_study.py`, `evaluate_http_test.py`) target the v0.3 repository layout and are kept
only for historical reproduction at tag `v0.3.0`.

## v0.2: repair, train, evaluate

- **Operational repair:** a bounded, usage-accounted inference retry recovers the
  previously failing partial-commit path. Qwen3-4B passed 3/3 targeted regression
  episodes; the original failure remains available.
- **Frozen data:** 72 training episodes, 8 development episodes and 24 test
  episodes, split by fault composition and record seed. No test trajectories train the model.
- **Actual local LoRA:** Qwen3-0.6B, 528 verified expert actions, 5.05M trainable
  parameters, BF16 on an 8GB GPU. Checkpoints are selected using development loss.
- **Paired outcomes:** the base and adapted model use the same prompt, decoding
  and action budget. See [complete results, failures and traces](../artifacts/v0.2/RESULTS.md).
- **Independent audit:** `python scripts/verify_experiment.py` checks split membership,
  weight selection, metrics and all test tool traces by replaying them against fresh databases.

The adapted policy completed **24/24** frozen composition tasks (21 recoveries,
3 appropriate escalations). The base model's failures are dominated by protocol
errors, even in an exploratory fence-tolerant control. This is evidence of a
working adapted policy, not an isolated measure of improved reasoning. This is imitation of a
scripted expert on one service, not an RL or external incident benchmark.

![Recorded training and paired evaluation, including protocol-confound disclosure](assets/post-training.png)

## v0.1: baseline on the SQLite sync service

On the ten public development scenarios, **Qwen3 4B (Q4_K_M) passed 9/10**:
eight verified recoveries and one correct read-only escalation, with zero false-success
claims. The remaining partial-commit case exhausted its generation budget. The
scripted reference passed 10/10. These are single-seed development results, not a
held-out benchmark or a training gain. The v0.1 release also passed 53 Python tests, browser
workflow checks and a clean wheel installation check. See the [full report and all episode
traces](../artifacts/RESULTS.md).
