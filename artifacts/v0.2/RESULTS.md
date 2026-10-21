# ResolveLab v0.2: local post-training experiment

With a parser accepting one enclosing JSON code block: **0/24 base → 24/24 LoRA**.
This control was added after observing test format failures, so it is **exploratory**.
Same Qwen3-0.6B revision, prompt, JSON protocol, greedy decoding and 18-action budget.
This is synthetic composition generalization in one service, with one training seed.

The pre-specified strict parser gave 0/24 → 24/24,
but every base episode failed at its first fenced JSON response, before executing
any tool. That contrast is dominated by **format compliance** and must not be
presented as a pure recovery-reasoning improvement. We retain it and report the
fence-only control rather than replacing the original denominator.

The fence-tolerant base also failed all 24 episodes: it read the runbook, then
returned malformed JSON for an unsupported completion. Thus the format control
does **not** remove the protocol confound. All base episodes share these initial
observations; they are not 24 independent reasoning failures. The supported claim
is successful deployment of the adapted policy on these tasks, not an isolated
gain in planning or general intelligence. Constrained decoding and a stronger
baseline on a fresh holdout are the next experiments.

| Policy | Pass | Writable tasks resolved | Correct escalation | False success | Errors | Median seconds |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3-0.6B base | 0/24 | 0/21 | 0 | 0 | 24 | 0.63 |
| Same base + LoRA | 24/24 | 21/21 | 3 | 0 | 0 | 9.38 |
| Base, fence-tolerant control | 0/24 | 0/21 | 0 | 0 | 24 | 2.18 |
| LoRA, fence-tolerant control | 24/24 | 21/21 | 3 | 0 | 0 | 9.23 |

Fence-tolerant paired outcomes: 24 wins,
0 regressions, 0 ties.
No weights, prompts, task definitions or budgets changed for the control; only
one complete outer code block can be removed. Prose extraction, invalid-schema
repair and action substitution remain disallowed. This addresses one observed
confound; it is not a fresh confirmatory holdout.

Strict-parser paired outcomes: 24 wins, 0 regressions, 0 ties.
Pass-rate change: +100.0 percentage points.
Exploratory 95% template-bootstrap interval: [100.0, 100.0] points;
only eight template clusters. Seeds within a template are correlated. This interval
does not include training variance or uncertainty from other tasks and domains.

## Training evidence

- 72 training episodes / 528 next actions; 8 dev episodes / 62 next actions.
- 5,046,272 LoRA parameters; 3 epochs,
  198 optimizer steps, seed 3407.
- 16.00 minutes on NVIDIA GeForce RTX 4060 Ti;
  peak allocated GPU memory 1.65 GiB.
- Selected **epoch-2** by minimum dev action-token loss,
  before running held-out model inference. No test-based checkpoint selection.
- Verified scripted demonstrations; no larger-model teacher or RL.

## Per-template outcomes

| Fault composition | Strict base | Strict LoRA | Fence control base | Fence control LoRA |
|---|---:|---:|---:|---:|
| mapping + partial | 0/3 | 3/3 | 0/3 | 3/3 |
| rate + partial | 0/3 | 3/3 | 0/3 | 3/3 |
| mapping + corrupt + lost | 0/3 | 3/3 | 0/3 | 3/3 |
| stale + corrupt | 0/3 | 3/3 | 0/3 | 3/3 |
| rate + lost + injection | 0/3 | 3/3 | 0/3 | 3/3 |
| mapping + readonly + stale | 0/3 | 3/3 | 0/3 | 3/3 |
| partial + stale + injection | 0/3 | 3/3 | 0/3 | 3/3 |
| mapping + rate + partial | 0/3 | 3/3 | 0/3 | 3/3 |

## Audit and reproduce

[`base-test.json`](base-test.json), [`sft-test.json`](sft-test.json) and the adjacent
trace directories retain every episode. The `*-format-test.json` files and their
trace directories retain both sides of the parser control. [`training.json`](training.json) includes
per-step losses, dependencies, hashes and memory. [`data/`](data/) contains the
portable train/dev JSONL and provenance. The old 4B development baseline remains
in [`../RESULTS.md`](../RESULTS.md), with its original failure intact.

```bash
python scripts/verify_experiment.py
```

This checks split membership, selected weight hash, paired metrics and every
published test trajectory by executing its tools again against a fresh database.
It needs no model or GPU. The [protocol](../../docs/post-training.md) gives full
training and evaluation commands, assumptions and limits.

The [partial-commit regression](partial-recovery.json) separately records 3/3
Qwen3-4B recoveries after a bounded inference retry. That retry permits more
generated tokens; it is not a matched model-size or cost comparison with SFT.

These numbers do not establish external adoption, production reliability, unseen
tool capability or superiority over a strong general-purpose agent. The test set
is now public; subsequent tuning requires a new holdout.
