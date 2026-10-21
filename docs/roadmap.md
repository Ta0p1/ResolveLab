# Roadmap

## v0.1 — Executable baseline

- Local workbench, Ollama integration, nine typed tools.
- Ten synthetic fault families with isolated persisted datasets.
- Independent data and permission checks.
- Durable traces, idempotency receipts and interrupted-run recovery.
- Reproducible offline and local-model measurements.

This release establishes the system and evidence. It does not claim training,
generalization, production deployment or external users.

## v0.2 — Composition holdout and first local SFT

Delivered: bounded inference recovery for truncated tool decisions; frozen
train/dev/test compositions; verified scripted training data; action-only LoRA;
development-loss checkpoint selection; paired base/SFT evaluation; failure traces;
GPU-free executable evidence replay; experiment view and reproduction protocol.

The scope is one model, one training seed and one synthetic service. Public test
results are an initial experiment, not evidence of broad agent capability. The
first test manifest must not become a tuning target while still called held-out.

## v0.3 — HTTP adapter and controlled decision evaluation

Delivered: a second service with actual HTTP transport, pagination, optimistic
concurrency and mid-task permission changes; a fresh registered composition holdout;
static tool-schema constrained baselines with shared one-shot prompting; a larger
1.7B baseline; three LoRA seeds with independent checkpoint selection; complete
HTTP traces, failure accounting and GPU-free evidence replay.

This is a synthetic backend, not a commercial SaaS integration. The CaseDesk model
is trained for its own contract; this is not zero-shot transfer from the sync model.
The HTTP backend's receipts are process-local, without restart durability.

## v0.4 — Stronger policies and durable external recovery

1. Collect off-policy failure states using train/development tasks, then freeze a
   new test set before optimizing recovery or performing preference/RL experiments.
   Expand independent record seeds and stratify target positions, pagination depth
   and task values; report those slices rather than only fault compositions.
2. Compare a larger reasoning model and stronger in-context strategies, reporting
   compute and token budgets alongside success, safety and latency.
3. Add persisted HTTP idempotency receipts, job leases, crash-injection tests and
   multi-process workers before making deployment reliability claims.
4. Integrate one real SaaS sandbox with authentication and least-privilege scopes.
5. Evaluate new tool/response schemas and genuinely unseen recovery mechanisms.

## Later

- Preference/RL experiments only when rewards resist obvious shortcuts.
- vLLM/OpenAI-compatible adapters with tested tool-protocol semantics.
- Real SaaS sandbox integrations, authentication and durable job leases.
- Contribution templates and public reproducibility reports.
