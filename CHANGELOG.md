# Changelog

## Unreleased

### Durable recovery

- Add `resolvelab.durable`: the CaseDesk HTTP contract and graders on a persisted SQLite store
  (WAL, `synchronous=FULL`, one `BEGIN IMMEDIATE` transaction per request), served by real
  uvicorn worker processes. The frozen `httpdesk` handlers run unchanged; their `state.lock` is
  the database transaction, so idempotency receipts, records and the commit log survive a
  restart and are shared between workers.
- Process faults: `crash_before_commit` and `crash_after_commit` (the worker exits through
  `os._exit` before or after the commit, without responding), `restart_after_commit` (every
  worker killed after the first write, restarted on the same store once a request fails) and
  `duplicate_delivery` (each PATCH sent to two workers at once). A separate fault ledger makes
  each fire once across workers.
- The `casedesk-durable-v1` suite: 14 compositions with the CaseDesk faults, two episodes each,
  generated in code from records disjoint from every registered episode. It is an engineering
  suite, not a registered study; the scripted teacher passes all 28.
- Add `grade_durable`: grader v2 on the state recovered after the episode, plus no duplicate
  commits per idempotency key, no lost acknowledged commits across boots and a fresh verifying
  read after the last restart.
- Tests cover crash after commit (a replayed key gets the saved 200 on the restarted worker),
  crash before commit (no write, receipt or event survives), restart, two-worker races with
  the same key, new keys and a reused key, and the teacher on every composition. Registered v2
  episodes (on one and two workers) and published v0.4 model traces, failures included, give
  identical observations and v2 verdicts on the durable store. Two wrong recoveries fail (a
  new-key write after a crash, a claim without a read after the restart), and the v0.3-style
  process-local store fails as a negative control.
- Add `resolvelab durable` (`episodes`, `run`, `suite`, `race`) through `main.py`, which is
  outside the study core, `examples/durable_recovery.py` (also run in CI) and
  `docs/durable-recovery.md`.
- No file under `httpdesk/`, `casedesk/` or `dialects/` changes, and no lock, result, manifest,
  trace or snapshot. No model was run.

### Fault proxy (milestone 1)

- Add `resolvelab.proxy`, milestone 1 of `docs/fault-proxy-design.md`: a proxy in front of an
  unchanged HTTP service, declared per scenario in YAML (or JSON). It matches on method, path
  template, a JSON body predicate and occurrence (the nth match, a list, every request, or only
  requests after a trigger), and its fault engine has `before`, `instead` and `after` hooks.
- Four faults, deterministic given the scenario, seed and agent actions: `rate_limit`
  (`Retry-After` and a virtual clock advanced by `/_resolvelab/wait`), `precondition` (412 or
  409 until the agent re-reads), `lost_ack` (the write commits, the agent gets 502) and
  `revoke` (403 on writes after the trigger; reads still pass).
- An episode log in JSONL: requests, faults, the service's answers, the responses the agent
  received, waits, the claim and both probe snapshots, with no wall-clock times and with
  credentials redacted. Replay re-sends a log and compares every record.
- A state probe of GET requests that bypass the proxy, and a rule grader for
  `allowed_changes`, `expected_state` and `exactly_once` (by idempotency key) that returns the
  CaseDesk verdict shape and failure categories. Rules planned for later milestones are refused,
  not ignored.
- A non-loopback upstream is refused unless the scenario lists its host in `allow_hosts`.
- `resolvelab proxy run | serve | grade | replay` through `main.py`. `run` takes the same
  `--model` provider specs as `resolvelab casedesk run`, except the CaseDesk-only `teacher` and
  `hf`.
- Tests against a toy order service: for each fault a correct scripted agent passes and a
  plausible wrong one fails (a new key after a lost acknowledgement, a write without a re-read,
  a retry that ignores `Retry-After`, a success claim after a revoke). Determinism, replay,
  redaction, the upstream allowlist, provider-driven episodes and the CLI are covered too.
- New dependency: PyYAML (`pyyaml>=6.0.1,<7`, pinned to 6.0.3 in `constraints.txt`), read with
  `safe_load` only.
- No file under `httpdesk/`, `casedesk/`, `dialects/`, `durable/` or `providers/` changes, and no
  lock, result, manifest, trace or snapshot. No model was run.

### Fault proxy (milestone 2: CaseDesk parity)

- `resolvelab.proxy.casedesk` runs a CaseDesk v2 episode behind the proxy: an unchanged CaseDesk
  service with its HTTP faults off, and a scenario that injects `rate_limit`, `revoke` and
  `lost_ack` in CaseDesk's order and declares the grading rules.
- `scripts/check_proxy_parity.py` replays every in-scope published v0.4 test episode (16 arms,
  960 episodes, every failure category) through it. The proxy's rules give grader v2's
  published verdict and failure category on all 960. Out of scope until actor requests exist
  (milestone 3): the compositions with `conflict` or `concurrent_resolve`.
- Scenario `clock`: a service's own wait endpoint (CaseDesk's `POST /clock`) is forwarded and
  also moves the virtual clock, logged as a `clock` record.
- `revoke.reads`: once the fault has refused a write, matching reads report the revocation
  (CaseDesk's `write_allowed: false`).
- New rules: `allowed_writes` (only declared writes may commit, which catches a wrong value later
  corrected), `redundant_writes` (a write to a resource that already had its expected values),
  and, brought forward from milestone 3, `fresh_verification` and `justified_escalation`. Rules
  count a repeated idempotency key once, so a retry answered from the service's receipt is not a
  new commit. The verdict gains `spurious_escalation`, in grader v2's precedence.
- `tests/test_proxy_parity.py`: a thinned published sample, and crafted sequences compared with
  grader v2 on the same actions.
- No locked file, lock, result, manifest, trace or snapshot changes. No model was run.

## 0.5.0 — 2026-11-04

### Release

- Version 0.5.0: the registered dialect transfer study with its evidence, the model providers
  and CLI, and the step-wise environment. In the locked source, only the `__version__` line
  changes, and every audit ignores it. No lock, result, manifest, trace or snapshot changes.
- A test now requires `pyproject.toml`, `__version__`, `CITATION.cff` and this changelog to
  agree on the version and its date.
- The wheel now carries the two benchmark files `resolvelab casedesk` reads, so the commands work
  outside a checkout. Without them the commands failed, and `hf:` models lost their pinned
  revision without warning. CI installs the built wheel and runs an episode from it.
- Correct the 0.4.0 date below to the day it was tagged and released.

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
- Add `examples/dialect_episode.py` (also run in CI), `docs/dialects.md` and a draft of the
  transfer protocol (`docs/dialect-transfer-protocol.md`), registered later in this release.
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
- This groundwork ran no model on a held-out dialect and changed no result, lock, manifest, trace
  or locked source file.

### Dialect transfer study (v0.5)

- Register the transfer protocol (2026-10-30), unchanged in design, before any model episode in a
  held-out dialect. Registration adds the run order and counts the dev evaluation in the compute
  estimate.
- Add `scripts/run_dialect_transfer.py`, the protocol's dev and test phases as a resumable job
  graph (the v0.4 runner with the dialect jobs).
- `scripts/dialect_transfer.py` opens the test pool for evaluation only, after the lock, with the
  locked source hash and adapters. `--contract study` evaluates on the study contract (the
  canonical dialect), the protocol's cost-of-diversity measurement; reports record the contract,
  the audit replays each episode in it, and the lock also refuses once such a report exists.
- Run the dev phase (38 of 38 jobs; no plumbing defect, no deviation) and lock the test phase
  (`artifacts/v0.5/test-lock.json`, 2026-10-31) before any test episode.
- `scripts/verify_dialect_transfer.py` checks the lock's inputs while the test phase runs. Once
  any result is published it runs the full audit, which now also checks the dev reports against
  the hashes frozen in the lock and recomputes the dev analysis.
- Add `scripts/package_dialect_transfer.py`, which copies the evidence into `artifacts/v0.5`
  and refuses an incomplete report or a test report that ran on unlocked sources.
- Publish the results (`artifacts/v0.5/RESULTS.md`, reports, traces, data and analyses). Q1:
  no adapter transfers fully. Q2: supported, `bc-multi − bc` = +13.3 pp, CI [1.1, 26.1], with a
  stated cost on the original contract. Q3: supported but fails safety non-inferiority,
  `dagger-multi − bc-volume-multi` = +14.2 pp, CI [4.2, 23.9]. The README shows both studies.
- Add `scripts/summarize_dialect_failures.py`, an exploratory failure taxonomy written after the
  results, which the audit recomputes. CI thins the dialect audit's replays as it does for v0.4.
- Add `scripts/make_dialect_figure.py`, the README figure rendered from the published bundle; a
  test fails if the committed figure differs from what the bundle produces.

### Audits

- The v0.3, v0.4 and v0.5 audits now replay on `artifacts/locked-source/<study>.zip`, in a process
  that can import nothing else from the package. A snapshot must reproduce its lock's source hash
  first, checked by code outside it. The audit commands are unchanged, and no lock, result or trace
  changed.
- `src/` must still match the snapshots, except `providers/`, `main.py`, `__main__.py`, `cli.py`,
  `api.py`, `casedesk/cli.py` and `casedesk/env.py`, which no script imports (a test walks the
  imports). Those can now be maintained; an edit to any other locked file still fails CI.
- CI edits two files outside the core and re-runs the source tests and the three audits, thinned.

### Documentation

- Bring the roadmap, study history and README layout table up to date with the merged work,
  mark v0.4 as released, and remove a leftover personal note from the roadmap.

## 0.4.0 — 2026-10-29

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
- Remove personal notes from the public docs. No result, lock, manifest, trace or
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
- Add a Post-training view, model card, reproduction commands and an updated demo;
  keep all v0.1 evidence intact.

## 0.1.0 — Initial executable baseline

Local workbench, Ollama native tools, transactional sync sandbox, independent SQL
outcomes, durable traces and public development measurements.
