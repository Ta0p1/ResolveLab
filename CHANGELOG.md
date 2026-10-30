# Changelog

## Unreleased

### Model adapters and CLI

- Add `resolvelab casedesk` (`episodes`, `run`, `eval`) and model providers: local
  Transformers (`hf:`, the study's exact decoding), Ollama (`ollama:`, the study's schema),
  any OpenAI-compatible server (`openai:`) and Claude through the Anthropic SDK
  (`anthropic:`, optional extra). Providers never repair or retry a decision; API keys stay in
  the environment. Hosted APIs get a portable root-object form of the action schema.
- A new `resolvelab.main` entry point dispatches `casedesk`; every other command still runs
  the original, locked `cli.py`; `python -m resolvelab` runs the same entry point. See
  `docs/models.md`.

### Environment interface

- Add `resolvelab.casedesk.env.CaseDeskEnv`, a step-wise environment (`reset` / `step` /
  `state`) over the same service, budget and grader, with a sparse verifiable reward and an
  opt-in guard for the public test pool. Tests replay published model traces through it and
  require identical observations, verdicts and diagnostics. `examples/casedesk_env_loop.py`
  and `docs/environment.md`.

### API dialects

- Add `resolvelab.dialects`: procedurally generated tool contracts over the unchanged CaseDesk
  service, faults and grader. A dialect renames tools, arguments, fields, values and errors and
  changes the concurrency token, pagination, status codes and time unit; `train` and `heldout`
  dialects use disjoint identifiers. The canonical dialect reproduces the study's prompt, schema
  and episodes exactly (tested), and every published v0.4 result translates through it unchanged.
- Add `examples/dialect_episode.py` (also run in CI), `docs/dialects.md` and a draft, unregistered
  transfer protocol (`docs/dialect-transfer-protocol.md`).
- Add the transfer-study plumbing: the episode-to-dialect assignment
  (`benchmarks/casedesk-dialects-v1.json`), a dialect-aware constrained policy, expert and DAgger row
  builders in dialects (the multi-dialect `train_core` rows are tested to be exactly v0.4's 396 `bc`
  states and actions), dialect evaluation, and `scripts/dialect_transfer.py`, which refuses the test pool.
- Add the dialect test lock and GPU-free audit (`scripts/lock_dialect_transfer.py`, which refuses an
  unregistered protocol, and `scripts/verify_dialect_transfer.py`). The new lock's source hash ignores
  the `__version__` line from the start.
- Add the registered analysis for the draft protocol (`scripts/analyze_dialect_transfer.py`): Q1 transfer
  per adapter with a paired-seed bootstrap, Q2/Q3 with the v0.4 statistics. It refuses the test pool
  without a lock, and the audit recomputes it.
- Add `scripts/check_dialect_decoder.py` (GPU): in the canonical dialect, `DialectPolicy` reproduced
  published v0.4 dev traces exactly (raw outputs, observations, verdicts; 6/6 `dagger-42`, 4/4
  `bc-volume-42` including two budget-exhausting failures).
- No model has been evaluated on held-out dialects; no result, lock, manifest, trace or locked source
  file changes.

### Documentation

- Bring the roadmap, study history and README layout table up to date with the merged work,
  mark v0.4 as released, list the draft v0.5 study as not run, and remove a leftover
  job-search line from the roadmap.

## 0.4.0 — 2026-10-28

### Release

- Version 0.4.0. Both locks (v0.3 and v0.4) were computed while `__init__.py` said 0.3.0, so
  `verify_http_study.py` and `verify_casedesk_v2.py` normalise exactly that one
  `__version__` line before hashing; every other byte of every locked file is still compared.

### Repository presentation (2026-10-27)

- Rewrite the README (and the Chinese README) around what the project is: fault-injected
  tool environments with side-effect grading. Lead with the v0.4 result, a light/dark result
  figure generated from the published bundle (`scripts/make_readme_figure.py`) and a no-GPU
  quick start; move the per-version narrative to `docs/history.md`.
- Add `examples/casedesk_quickstart.py` (one fault-injected episode plus two replayed model
  runs, about two seconds; also run in CI), a docs index, `CITATION.cff` and package metadata.
- Remove personal job-search notes from the public docs. No result, lock, manifest, trace or
  locked source file changes.

### v0.4 study (2026-10-22/23)

- Review the v0.3 result against its own traces: three effective test records, a base model
  that never reached a fault, target slot confounded with the one-shot demo, position-encoding
  IDs, two latent grader holes (no published verdict changes) and a teacher that mislabels
  learner states. Add a counterfactual position sweep on the v0.3 adapters.
- Add `resolvelab.casedesk`: independent-record benchmark with declared factors, an
  off-policy-safe teacher with replay-verified labels, grader v2, DAgger data collection with
  a size-matched behaviour-cloning control, hierarchical seed × record bootstrap and exact
  McNemar tests, resumable memory-aware job runner, test lock and GPU-free verifier.
- Register the study before any v2 model run; amend once (two extra baselines with fixed
  inclusion rules) before running them; lock all test inputs before the first test episode.
- Result: DAgger 98.3% vs size-matched BC 90.8% (+7.5 pp, CI [1.9, 13.3]); v0.3 adapters
  29.4% on independent records. All failures, baselines and the dev-only thinking baseline
  are published in `artifacts/v0.4/`.
- The v0.3 audit now hashes exactly the v0.3 file set, so it still reproduces the v0.3 lock.

## 0.3.0 — 2026-10-21

- Add CaseDesk, a second synthetic service behind real HTTP sockets, with paginated
  lookup, ETag/If-Match, idempotency keys, post-commit 502, Retry-After and permission
  revocation. Keep the adapter free of hidden retries or scripted recovery.
- Independently reject wrong-record writes, stale verification, redundant commits
  and unjustified escalations, with real-HTTP contract and concurrency tests.
- Register a fresh 48/8/30 train/development/test split before model runs. Strengthen
  the development-tested baseline with a shared training demonstration and full
  static schema constraints; report serialization validity separately from outcomes.
- Run three Qwen3-0.6B LoRA seeds with development-loss checkpoint selection and a
  matched 0.6B comparison, plus a larger Qwen3-1.7B baseline. Preserve every test failure.
- Add a separately registered Qwen3-4B Q4_K_M / Ollama control; disclose its distinct
  inference backend and retain development prompt comparisons separately from test.
- Add per-episode HTTP inspection, raw traces, reproducibility locks and GPU-free
  executable audits. Retain v0.1/v0.2 results and their limitations.
- Keep atomic report writes reliable during brief Windows rename denials; preserve
  the previous complete report and fail after bounded retries on permanent errors.

## 0.2.0 — 2026-10-21

- Recover a zero-tool-call generation cutoff with one bounded inference retry;
  retain usage from both attempts and preserve the original failed episode.
- Freeze disjoint train/dev/test compositions and validate training provenance.
- Add optional Transformers/PEFT inference and action-only LoRA training with
  development-loss checkpoint selection, weight hashes and memory measurements.
- Publish the actual local 0.6B experiment: 528 supervised actions, 24/24 SFT
  test passes, original strict-parser comparison and an exploratory code-fence
  control. Explicitly document baseline protocol failures and limited scope.
- Re-execute all 120 published test tool trajectories without a GPU to audit
  outcomes, alongside split, metric and adapter-selection checks.
- Add a Post-training view, model card, reproduction commands, updated demo and
  resume material; keep all v0.1 evidence intact.

## 0.1.0 — Initial executable baseline

Local workbench, Ollama native tools, transactional sync sandbox, independent SQL
outcomes, durable traces and public development measurements.
