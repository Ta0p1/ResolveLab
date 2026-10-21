# CaseDesk HTTP study — v0.3

Registered synthetic composition holdout; real local inference and real HTTP transport.

Across three registered LoRA seeds, task success ranged from **66.7% to 100.0%** (mean 77.8%, sample SD 19.2 percentage points). The matched 0.6B baseline passed **0/30**; the larger 1.7B baseline passed **12/30**.

Every primary model arm had **100% schema-valid calls**. Thus the observed task-success differences are not attributable to rejected JSON or invalid tool schemas.

| Model / seed | Passed | Resolved | Escalated | Valid calls | Unsafe writes | False success | Redundant writes | Median seconds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-0.6B base | 0/30 | 0 | 0 | 100.0% | 0 | 10 | 0 | 3.14 |
| Qwen3-1.7B base | 12/30 | 8 | 4 | 100.0% | 10 | 14 | 3 | 9.42 |
| 0.6B LoRA / 3407 | 20/30 | 16 | 4 | 100.0% | 0 | 0 | 0 | 15.98 |
| 0.6B LoRA / 42 | 30/30 | 24 | 6 | 100.0% | 0 | 0 | 0 | 13.89 |
| 0.6B LoRA / 2026 | 20/30 | 16 | 4 | 100.0% | 0 | 10 | 0 | 9.59 |

Pass includes verified resolution or a justified escalation after an actual target-ticket 403. Unsafe writes count committed wrong-record/incorrect-value mutations; redundant writes count commits whose prior priority/status already matched the request. A redundant write to the wrong record also counts as unsafe. HTTP errors such as 412/429/502 are expected task observations, not automatic failures.

## Supplementary 4B control

Qwen3-4B Q4_K_M through Ollama passed **6/30**, with 100.0% schema-valid calls, 0 unsafe writes, 3 false success claims and 9.33s median episode time. [Raw report](ollama-4b-test.json).

This separately registered control uses the same base contract, example, schema and nominal action/token limits, with the original prompt selected on development tasks. Quantization, inference backend, chat template details and grammar engine differ, so it is not a matched training comparison. Its 30 episodes are additional to the primary 150. Latency retains model-load time; a lower parameter count alone does not establish a speed or cost advantage.

## Matched 0.6B comparisons

| Training seed | Wins | Regressions | Ties | Gain (pp) | Template-bootstrap 95% interval (pp) | Wins with valid calls in both arms |
|---|---:|---:|---:|---:|---|---:|
| 3407 | 20 | 0 | 10 | 66.7 | [66.7, 66.7] | 20 |
| 42 | 30 | 0 | 0 | 100.0 | [100.0, 100.0] | 30 |
| 2026 | 20 | 0 | 10 | 66.7 | [66.7, 66.7] | 20 |

Intervals resample the 10 templates (10,000 bootstrap draws, seed 2026), not 30 supposedly independent incidents. The same three record seeds appear across templates. Shared fault mechanisms create further dependence; these descriptive intervals do not bound production reliability. The 1.7B model is a size control, not a paired training effect.

## Failure accounting

JSON Schema controls tool names, argument types and enum values. It does **not** guarantee that copied strings are valid HTTP header values or identify the correct record. The following post-hoc diagnostics retain all episodes in the primary denominator. Each episode receives one prioritized failure category; unsafe, redundant and false-success counters can overlap. Thus the false-success category alone is not the total number of false success claims.

| Policy | Episodes with transport/header errors | Such failed calls | Failed episodes with valid calls and no transport/header error |
|---|---:|---:|---:|
| Qwen3-0.6B base | 0 | 0 | 30 |
| Qwen3-1.7B base | 3 | 3 | 15 |
| 0.6B LoRA / 3407 | 0 | 0 | 10 |
| 0.6B LoRA / 42 | 0 | 0 | 0 |
| 0.6B LoRA / 2026 | 0 | 0 | 10 |
| Supplementary 4B | 0 | 0 | 24 |

These remaining failures concern action selection, argument values or outcome verification; they do not by themselves isolate a general reasoning capability.

- **Qwen3-0.6B base:** false_success: 10, unjustified_escalation: 20 [Example raw failure](base-test/test_conflict_lost-6301.json).
- **Qwen3-1.7B base:** false_success: 2, redundant_write: 2, unjustified_escalation: 4, unsafe_mutation: 10 [Example raw failure](large-test/test_conflict_lost-6302.json).
- **0.6B LoRA / 3407:** tool_budget: 10 [Example raw failure](sft-3407-test/test_conflict_lost-6303.json).
- **0.6B LoRA / 42:** no failed episodes in this test.
- **0.6B LoRA / 2026:** false_success: 10 [Example raw failure](sft-2026-test/test_conflict_lost-6303.json).
- **Supplementary 4B control:** redundant_write: 3, tool_budget: 21.

## One compound case, without changing the denominator

The following view uses `test_conflict_rate_lost / 6301`: the triple-fault template and its first registered record seed. LoRA seed 3407 is the first registered training seed, not the best-scoring seed. All other cases and training seeds remain in the tables and raw bundle.

**0.6B baseline: FAIL** — false_success; 0 committed writes. [Exact arguments and state](base-test/test_conflict_rate_lost-6301.json).

`list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `finish(resolved)`

**1.7B baseline: PASS** — resolved; 1 committed writes. [Exact arguments and state](large-test/test_conflict_rate_lost-6301.json).

`list_tickets(200)` → `list_tickets(200)` → `get_ticket(200)` → `patch_ticket(429)` → `wait(200)` → `patch_ticket(412)` → `get_ticket(200)` → `patch_ticket(502)` → `get_ticket(200)` → `finish(resolved)`

**0.6B LoRA / 3407: PASS** — resolved; 1 committed writes. [Exact arguments and state](sft-3407-test/test_conflict_rate_lost-6301.json).

`list_tickets(200)` → `list_tickets(200)` → `get_ticket(200)` → `patch_ticket(429)` → `wait(200)` → `get_ticket(200)` → `patch_ticket(412)` → `get_ticket(200)` → `patch_ticket(502)` → `get_ticket(200)` → `finish(resolved)`

**Supplementary 4B control: FAIL** — unfinished; 0 committed writes. [Exact arguments and state](ollama-4b-test/test_conflict_rate_lost-6301.json).

`list_tickets(200)` → `list_tickets(200)` → `get_ticket(200)` → `patch_ticket(429)` → `wait(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)` → `list_tickets(200)`


## Record-seed coverage (post-hoc diagnostic)

| Record seed | Target index (zero-based) | 0.6B base | 1.7B base | LoRA 3407 | LoRA 42 | LoRA 2026 | 4B control |
|---|---:|---:|---:|---:|---:|---:|---:|
| 6301 | 3 | 0/10 | 7/10 | 10/10 | 10/10 | 10/10 | 3/10 |
| 6302 | 3 | 0/10 | 5/10 | 10/10 | 10/10 | 10/10 | 3/10 |
| 6303 | 0 | 0/10 | 0/10 | 0/10 | 10/10 | 0/10 | 0/10 |

Target indices by split: train `[3, 5, 1, 4, 4, 3]`, development `[4, 3]`, test `[3, 3, 0]`. This coverage audit was performed after test inference began, not used to change the locked data. The first-record target is absent from training/development. Repeated pagination on that record exposes a real coverage/generalization gap, despite successful development rollouts. Position is correlated with the other values in each seed, so this is a diagnostic hypothesis, not an isolated causal attribution.

Template-bootstrap intervals above condition on these three record variants. If errors are shared across templates for one seed, those intervals can be artificially narrow or even degenerate; they do not capture record-distribution uncertainty. More independent records and a new holdout are needed before a reliability claim. The published test is not reused for training or model selection.

## Inference resource accounting

| Primary arm | Mean tool actions / episode | Total output tokens | Total input tokens |
|---|---:|---:|---:|
| Qwen3-0.6B base | 5.00 | 2600 | 277720 |
| Qwen3-1.7B base | 7.63 | 6530 | 455772 |
| 0.6B LoRA / 3407 | 13.27 | 8796 | 1026124 |
| 0.6B LoRA / 42 | 7.57 | 6524 | 456552 |
| 0.6B LoRA / 2026 | 6.93 | 5426 | 412984 |

Counts include failed episodes and repeated reads. A fast incorrect termination is not an efficient recovery. These unmerged PEFT rollouts and constrained HF decoding are not serving-throughput benchmarks; compare the full success/cost tradeoff. The supplementary Ollama backend reports cached/prefill counts differently, so its raw usage is retained without combining input-token totals.

## Training and reproducibility

| Seed | Selected checkpoint | Dev action loss | Training seconds | Peak allocated GiB |
|---|---|---:|---:|---:|
| 3407 | epoch-3 | 0.000198 | 783.2 | 1.70 |
| 42 | epoch-3 | 0.000191 | 783.3 | 1.70 |
| 2026 | epoch-3 | 0.000250 | 777.8 | 1.71 |

48 training episodes / 322 verified scripted actions; 8 development episodes / 58 actions. Action-only LoRA rank 8, 5,046,272 trainable parameters, BF16 on an RTX 4060 Ti 8GB. Three epochs per seed. All primary arms share the same training demonstration, prompt, static grammar, 24-action limit, 192 generated tokens per action and 8192-token context. Greedy non-thinking decoding, no hidden retry or rule fallback.

The manifest was committed before model runs (`7e5ffb4`). The [training lock](training-lock.json) and [test lock](test-lock.json) pin data, code, prompt/schema and selected adapters. Development-only prompt improvements preceded the test lock; see the amendment in the [registered protocol](../../docs/httpdesk-protocol.md). No test outcome was used to select a checkpoint or seed.

Run `python scripts/verify_http_study.py` to check split membership, hashes, checkpoint selection, metrics and all 180 model episodes (150 primary + 30 supplementary) by executing recorded actions through fresh HTTP sockets. This audits environment outcomes, not exact model token regeneration on arbitrary hardware.

## Limits

- Synthetic process-local ticket backend; no real SaaS account, production users or restart-durable remote receipts.
- Known API and fault primitives; held-out compositions are not unseen domains or zero-shot service transfer.
- Fixed task wording and only three distinct test record seeds. No paraphrase-robustness claim; episode count is not a count of independent customer requests.
- End-to-end gains include exact reference matching, argument copying and workflow following. A baseline that never reaches an injected HTTP fault does not isolate recovery reasoning for that fault.
- Only three training seeds, one small fine-tuned model family and one training dataset. This does not establish general agent reasoning gains.
- The one-shot, greedy non-thinking baselines are stronger than an unconstrained parser-only baseline, but are not frontier-agent or best-possible prompting comparisons.
- Test tasks are now public. Further tuning requires a new holdout and a new experiment name.
- Equal token/action budgets do not imply equal compute, latency or cost across model sizes.
