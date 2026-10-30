# API dialects

`resolvelab.dialects` generates new tool contracts that keep CaseDesk's service, faults and grader. It is
infrastructure for the transfer question on the [roadmap](roadmap.md): does what an agent learned on
one contract (fault recovery, verification, escalation) carry over to an API it has never seen? **No model
has been evaluated on it yet**; this page describes the environment and the checks behind it. The
study is a [registered protocol](dialect-transfer-protocol.md) (2026-10-30) and has not finished.

## What a dialect changes

A dialect is drawn by `generate(seed, split)`. It renames, and changes conventions:

| Surface | Study contract | Examples of dialect choices |
| --- | --- | --- |
| Tools | `list_tickets`, `patch_ticket`, `finish` … | `scan_bookings`, `amend_booking`, `conclude` |
| Arguments and record fields | `ticket_id`, `etag`, `idempotency_key`, `external_ref` | `booking_key`, `seq`, `op_id`, `client_ref` |
| Values | priorities `low…urgent`, statuses, outcomes | `sev4…sev1`, `queued/paused/settled`, `success/human_review` |
| Error strings | `precondition_failed`, `rate_limited` … | `version_mismatch`, `busy` … |
| Concurrency token | quoted ETag `"v5"` | integer revision `5`, weak ETag `W/"5"`, version tag `rev-5` (in a header field or the body) |
| Pagination | `page-N` cursors | opaque per-episode tokens, integer offsets, page numbers |
| Status codes | 412, 429, 502, 403 | 409, 503, 504, 423 (key reuse moves to 422 when 409 means conflict) |
| Time unit | seconds | milliseconds for waits and the rate-limit hint |

The system rules, tool descriptions, task wording (all six registered phrasings) and the one-shot
demonstration are templates over these names. The demonstration is the study's own demo episode,
translated action by action.

## What it keeps

Each dialect action is validated against the dialect's schema, translated to the canonical action and
sent to the unchanged CaseDesk HTTP service. The result is translated back. The trace keeps the canonical
observations, so the grader (`grade_v2`), `diagnose` and the off-policy teacher see exactly what they see
in the study. A dialect changes what the agent must read and write, never what counts as success.

A token the agent mangles is passed through as written and the service rejects it as stale, exactly as a
mis-copied ETag is rejected in the study. That keeps the self-inflicted conflict loop, the failure DAgger
removed in v0.4, observable in every dialect.

## Splits

`train` and `heldout` dialects draw every identifier from disjoint word pools, and no held-out identifier
is a study identifier. The structural conventions (token style, pagination, codes, unit) occur in both
splits, so a held-out dialect is lexically new but structurally familiar. A generated dialect in which two
names the agent must tell apart coincide (two arguments, two record fields, two status codes with
different meanings) is rejected at construction.

## Checks (`tests/test_dialects.py`)

- The canonical dialect reproduces the study's prompt for every phrasing, its action schema, and four
  dev episodes step by step: every conversation the policy saw, every observation and the verdict.
- Translating any published v0.4 test result through the canonical dialect returns it unchanged
  (all status codes the models met, including 0, 400 and 404).
- Published model actions rewritten into a dialect (integer revisions, offsets, milliseconds) meet the
  same service results and verdicts when replayed.
- Train and held-out identifiers are disjoint over 300 seeds each, and held-out prompts show no study
  identifier in the tool catalog, the demonstration or the rules.
- The scripted teacher passes fault compositions (conflict + rate limit + lost acknowledgement,
  concurrent resolve, revoke + lost acknowledgement) in train and held-out dialects.
- A mangled token in each of the four styles returns the dialect's conflict code and commits nothing;
  millisecond dialects translate the rate-limit hint and waits; unknown opaque cursors are rejected;
  invalid actions (a study tool name in a held-out dialect, missing arguments) end the episode before
  any request.

## Use

```python
from resolvelab.dialects import generate, run_dialect_episode

dialect = generate(3, "heldout")
# policy.next(messages) returns (action, usage, seconds)
trace = run_dialect_episode(spec, dialect, policy=my_policy)
```

`python examples/dialect_episode.py` runs one registered test episode in a held-out dialect next to the
study's API. A policy receives the dialect conversation and returns a dialect action;
`Translator(dialect).schema()` is the JSON schema for constrained decoding.

## Study plumbing

For the [transfer protocol](dialect-transfer-protocol.md):

- `benchmarks/casedesk-dialects-v1.json` assigns every registered episode its own dialect: train pools and
  dev get `train` dialects (dev seeds unused by training), test gets `heldout` ones. It pins the generated
  dialects by hash, so a later change to a word pool is detected on load.
- `dialects.policy.DialectPolicy` is the v0.4 constrained decoder (LM Format Enforcer, field order
  forced, same budgets) with the episode's dialect schema, validating its output against the dialect.
  In the canonical dialect it reproduces published v0.4 dev traces output for output
  (`scripts/check_dialect_decoder.py`, GPU).
- `dialects.data` builds expert and DAgger rows in dialects. Labels come from the v0.4 teacher on the
  canonical form of the learner's prefix and are kept only if the teacher's continuation passes grader
  v2; targets are rendered back into the dialect. The trainer is v0.4's, unchanged.
- `dialects.evaluate` writes the v0.4 report format plus each episode's dialect, token style,
  pagination, time unit and conflict code.
- `scripts/dialect_transfer.py` runs collect-expert, rollout, assemble, train and eval with the v0.4
  configuration. The test pool is evaluation only, after the lock, with the locked sources and
  adapters. `--contract study` runs the episodes on the study contract instead (the cost-of-diversity
  measurement); the report records which.
- `scripts/run_dialect_transfer.py dev|test` runs the protocol's phases as a resumable job graph.
- `dialects.lock` and `dialects.audit`, with `scripts/lock_dialect_transfer.py` and
  `scripts/verify_dialect_transfer.py`: the test lock (it refuses an unregistered protocol) and a
  GPU-free audit that re-derives every DAgger label and replays every test episode in its dialect.
- `dialects.analysis` and `scripts/analyze_dialect_transfer.py`: the registered analysis (Q1 transfer
  per adapter with a paired-seed bootstrap; Q2/Q3 with the v0.4 statistics), recomputed by the audit.

## Limits

- The underlying service is CaseDesk's: same record shapes, same fault mechanics. A dialect tests
  transfer across contracts, not across domains.
- Lexical disjointness covers API identifiers. Task wording keeps its English phrasing (one phrasing says
  "Customer case"), and HTTP verbs in tool descriptions are unchanged.
- Millisecond waits are rounded up to whole seconds by the service clock; rate-limit hints are always
  whole seconds.
