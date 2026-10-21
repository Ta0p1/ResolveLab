# ResolveLab CaseDesk LoRA policy — v0.3

## Intended use

Research and portfolio demonstration of small-model tool selection and recovery
within the published synthetic CaseDesk contract. This is not a customer-support
production model. It has no access to arbitrary URLs, shell commands or real tickets.

Base: `Qwen/Qwen3-0.6B`, pinned revision
`c1899de289a04d12100db370d81485cdf75e47ca` (upstream Apache-2.0).
Adapters: LoRA rank 8, alpha 16, dropout 0.05, all attention and MLP projections;
5,046,272 trainable parameters. Training seeds: 3407, 42, 2026, all reported.

## Data and optimization

48 synthetic training episodes provide 322 independently verified scripted expert
actions. Eight development episodes provide 58 actions. Records and mechanism
compositions are disjoint across splits. The 30 test episodes were registered before
model runs; no test trajectories are training examples. The shared inference prompt
contains one complete training demonstration (`train_plain`, seed 4101).
The training set reuses six record seeds under eight fault settings; development
reuses two seeds under four settings, and test reuses three seeds under ten settings.
These are episode counts, not counts of independent natural-language requests.
The task wording and tool contract are fixed; paraphrase robustness is untested.

Three epochs of action-only causal-LM loss; BF16, AdamW at 2e-4, gradient accumulation
8, warmup 10 optimizer steps followed by cosine decay, gradient clipping 1.0 and
gradient checkpointing. Select each seed's minimum development action-token loss.
No RL, DPO, teacher-model distillation or test-driven checkpoint selection is used.

## Inference contract

Use the exact prompt, tool descriptions and schema in `httpdesk/schema.py`, the
bundled training demonstration and the constrained policy in `httpdesk/policy.py`.
LM Format Enforcer 0.11.3 enforces a static union of tool-call schemas with fixed
field order. Every tool remains available at every step. Greedy non-thinking
decoding, 192 generated tokens per action, 8192-token context, 24 actions per task.
There is no parser repair, model-output retry or scripted fallback.

Schema-valid output is still independently validated at runtime. A decoder can hit
its token budget or produce unsupported constraints; these failures stay in the
denominator. IDs, ETags, cursors and idempotency keys are unconstrained strings, so
semantic errors remain possible even when every call is schema-valid.

## Evaluation and limits

See [all results and failures](../artifacts/v0.3/RESULTS.md) and the
[registered protocol](httpdesk-protocol.md). Baselines use the same schema, prompt
and budgets, including a larger Qwen3-1.7B model. The same-size comparison isolates
the adapter effect under this fixed inference setup, not an inherent capability
gain independent of prompting, model family or decoding strategy.

A separately registered Qwen3-4B Q4_K_M / Ollama control uses the same base contract,
example, schema and nominal budgets. A task-continuity reminder was rejected on development data.
Its quantization, backend, chat-template details and
grammar implementation differ; it is a practical reference rather than a matched
training comparison. Its raw results and failure traces are reported separately.

This is a narrow, now-public composition benchmark. Similar references, scripted
fault timing and deterministic task generation do not reproduce the full diversity
of real support systems. Test cases are correlated by template and record seed.
The three training seeds measure optimization variation on one dataset; they do
not estimate generalization across datasets. In-memory HTTP backend state does not
persist across restart. Unseen APIs, production users and frontier-agent comparisons
remain untested.

Weights are generated locally by the reproduction commands. Model and adapter
hashes, training logs, exact data and raw test traces are published in the repository;
the repository does not bundle base model weights.
