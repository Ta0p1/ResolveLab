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

## v0.4 — Self-review and a controlled DAgger study (released as 0.4.0, 2026-10-29)

Delivered: a review of v0.3 against its own traces and a counterfactual showing the v0.3
adapters copied the demo's layout; an independent-record benchmark with stratified target
slots, decoy shapes and held-out wording; an off-policy-safe teacher with replay-verified
labels; grader v2; a registered DAgger vs size-matched behaviour-cloning comparison (98.3% vs
90.8%, +7.5 pp, CI [1.9, 13.3]); stronger in-context and thinking-mode baselines (neither
helped); test lock and a GPU-free verifier that re-derives every DAgger label.

## v0.5 — Transfer to unseen API dialects (released as 0.5.0, 2026-11-04)

- `resolvelab casedesk` and model providers (local Transformers, Ollama, OpenAI-compatible
  servers, Claude), so a model served by any of these can be evaluated on the registered
  benchmark.
- `CaseDeskEnv`: the same service, budget and grader as a step-wise environment with a
  verifiable reward.
- Contribution workflow: PR and issue templates, pre-commit, Dependabot, security policy.
- Generated API dialects and the tooling for a transfer study: assignment, dialect-aware
  constrained policy, training rows, evaluation, lock, GPU-free audit and analysis.
- The v0.5 transfer study: [registered protocol](dialect-transfer-protocol.md) and
  [results](../artifacts/v0.5/RESULTS.md). Training across dialects helps on unseen contracts,
  DAgger helps most, and `dagger-multi` fails the registered safety limit against its control.
- Audits that replay on hash-checked snapshots of the locked source, so files no study ran can
  be maintained without touching a lock.

## Direction from 0.6: reliability testing for agents on real APIs

Through v0.5 ResolveLab answered research questions on one synthetic service. The method is
what carries over: inject the failures that change the correct next action, and grade the
agent from the system's state and the request log rather than from its claim. From 0.6 the
work makes that method usable on services other than CaseDesk, while studies keep the
registration, lock and audit rules above.

### 0.6 — Fault proxy and declarative grading

- A fault proxy that runs in front of any HTTP service and injects rate limits, precondition
  conflicts, lost acknowledgements, revoked permissions, concurrent writers and injected
  text, with a declarative grader over state snapshots and the request log
  ([design](fault-proxy-design.md)).
- Acceptance test: CaseDesk behind the proxy reproduces grader v2 verdicts on the published
  v0.4 traces.
- Durable recovery: persisted idempotency receipts, crash injection between commit and
  response, process restart and multi-worker races. Implemented (unreleased) for CaseDesk as
  `resolvelab.durable`, with an exactly-once grader on top of grader v2
  ([durable recovery](durable-recovery.md)).

### 0.7 — More domains and hosted-model results

- Two reference services outside ticketing where side effects are expensive: refunds with
  idempotency, and inventory with concurrent reservations.
- Published results for hosted and local models on every service, reported by pass rate,
  each safety category, tokens and latency.
- MCP server mode and native tool calling, alongside the JSON action format.

### 0.8 — Training on verified data at larger scale

- Teacher labels from a strong model, kept only when the grader verifies the continuation, to
  replace the hand-written runbook where none exists.
- Larger trained models than 0.6B, and RL on the step-wise environments now that the reward
  is grounded in server state.
- OpenEnv and verifiers packaging of the environments.

### Studies

Registered studies continue alongside, one at a time:

- Safety after transfer: `dagger-multi` still claims success on partial matches and commits
  wrong values in unseen dialects ([results](../artifacts/v0.5/RESULTS.md)). A study can target
  those states directly, on a fresh test pool; the v0.5 result is not reinterpreted.
- A token-matched control and more DAgger iterations, if the v0.4 effect is to be sized
  rather than only detected.

## Later

- A GitHub Actions workflow that runs scenarios on every pull request and posts a report.
- Integrations with real SaaS sandboxes, with authentication, least-privilege scopes and
  cleanup.
- vLLM-specific serving checks beyond the OpenAI-compatible provider.
- Public reproducibility reports from outside contributors.
