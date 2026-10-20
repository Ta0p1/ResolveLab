# Roadmap

## v0.1 — Executable baseline

- Local workbench, Ollama integration, nine typed tools.
- Ten synthetic fault families with isolated persisted datasets.
- Independent data and permission checks.
- Durable traces, idempotency receipts and interrupted-run recovery.
- Reproducible offline and local-model measurements.

This release establishes the system and evidence. It does not claim training,
generalization, production deployment or external users.

## v0.2 — Stronger evaluation before training

1. Add genuinely different service adapters and fault compositions, including
   pagination, timestamp windows, conflicting updates and authorization changes.
2. Freeze train/development/test manifests by task template, not merely data seed.
3. Evaluate at least two local model sizes with a fixed budget and full traces.
4. Add prompt and recovery-strategy ablations with unchanged graders.
5. Report invalid-call rate, intervention rate, latency distributions and all failures.

Acceptance criterion: an external contributor can reproduce results and explain
every failed episode without relying on a screenshot or a selected success story.

## v0.3 — Reviewed trajectories and SFT

1. Generate teacher trajectories on training environments only.
2. Filter with executable outcome checks and review ambiguous cases.
3. Preserve task, environment, model, prompt and reviewer provenance.
4. Train a small model with a reproducible adapter-based SFT configuration.
5. Compare base versus SFT on the frozen held-out set at the same action budget.

No GPU training is scheduled or charged by this release. Select a model, license,
dataset and compute plan before launching a training experiment.

Acceptance criterion: any claimed gain survives held-out evaluation and does not
trade off data correctness, permission boundaries or false-success rate.

## Later

- Preference/RL experiments only when rewards resist obvious shortcuts.
- vLLM/OpenAI-compatible adapters with tested tool-protocol semantics.
- Real SaaS sandbox integrations, authentication and durable job leases.
- Contribution templates and public reproducibility reports.
