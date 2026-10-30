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

## v0.4 — Self-review and a controlled DAgger study (delivered, unreleased)

Delivered: a review of v0.3 against its own traces and a counterfactual showing the v0.3
adapters copied the demo's layout; an independent-record benchmark with stratified target
slots, decoy shapes and held-out wording; an off-policy-safe teacher with replay-verified
labels; grader v2; a registered DAgger vs size-matched behaviour-cloning comparison (98.3% vs
90.8%, +7.5 pp, CI [1.9, 13.3]); stronger in-context and thinking-mode baselines (neither
helped); test lock and a GPU-free verifier that re-derives every DAgger label.

## v0.5 — candidates, one at a time

1. Durable recovery as an engineering loop: persisted HTTP idempotency receipts, crash
   injection between commit and response, process restart and multi-worker races.
   Strongest fit for application-engineering roles.
2. Transfer: a second contract with different tools/schemas, evaluated zero-shot and after
   a small amount of DAgger, to test whether learner-state labels help beyond one contract.
   The environment exists: [generated API dialects](dialects.md) with lexically disjoint
   train and held-out splits over the same service and grader. The study is a
   [draft protocol](dialect-transfer-protocol.md), not registered.
3. Token-matched control and more DAgger iterations, if the v0.4 effect is to be sized
   rather than only detected.
4. A real SaaS sandbox with authentication, least-privilege scopes and cleanup.

## Later

- Preference/RL experiments only when rewards resist obvious shortcuts.
- vLLM/OpenAI-compatible adapters with tested tool-protocol semantics.
- Real SaaS sandbox integrations, authentication and durable job leases.
- Contribution templates and public reproducibility reports.
