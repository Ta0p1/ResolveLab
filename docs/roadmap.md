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

## v0.3 — External integration and stronger generalization evidence

1. Implement a second sandbox adapter with a real HTTP boundary, pagination,
   optimistic concurrency and permissions changing during a task.
2. Add task and tool-schema variation, then freeze a new holdout before tuning.
3. Compare stronger models and recovery strategies at explicitly matched budgets.
4. Repeat training with at least three seeds; report distributions and regressions.
5. Introduce off-policy failure states to reduce expert-trajectory exposure bias.
6. Add server job leases and multi-process recovery before expanding deployment.

Acceptance: another developer can reproduce the comparison, replay every failure
and identify which reliability guarantees survive the external API boundary.

## Later

- Preference/RL experiments only when rewards resist obvious shortcuts.
- vLLM/OpenAI-compatible adapters with tested tool-protocol semantics.
- Real SaaS sandbox integrations, authentication and durable job leases.
- Contribution templates and public reproducibility reports.
