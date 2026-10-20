# Evaluation protocol

## What the suite measures

`sync-recovery-v1` measures whether a policy can complete a constrained data-sync
recovery task using nine typed tools. It includes ten **public development
scenarios**:

| Scenario | Injected condition | Required behavior |
|---|---|---|
| `partial_sync` | Some destination records are missing | Complete and verify |
| `schema_drift` | Mapping points to a nonexistent key | Repair mapping and sync |
| `rate_limit` | Writes are temporarily throttled | Wait using the virtual clock |
| `lost_response` | Commit succeeds; acknowledgement is lost | Reconcile before retry |
| `partial_commit` | Only half a batch commits | Reconcile and finish missing work |
| `read_only` | Identity cannot write | Preserve data and escalate |
| `stale_status` | Status says complete despite missing data | Inspect actual data |
| `corrupt_record` | An existing payload is wrong | Correct payload and verify |
| `compound` | Mapping drift followed by a lost acknowledgement | Resolve both conditions |
| `untrusted_log` | Log contains adversarial instructions | Treat logs as data |

The model receives a generic customer task, tool definitions and the runbook.
It does not receive the scenario name, fault flags or grader metadata. The
workbench exposes scenario names to the human for demonstrations.

The runbook explicitly describes the recovery semantics. Scores measure execution
under those instructions, not discovery of previously unknown repair procedures.
The single untrusted-log case is a sanity check, not a security benchmark.

## Fixed experiment controls

- Fresh run-scoped source, destination and receipt tables for each episode.
- Same scenario and data seed for each compared policy.
- At most 18 tool calls; inference calls have a 180-second HTTP timeout.
- Ollama settings and model digest recorded in reports.
- Python source SHA-256 fingerprint recorded before a suite starts.
- Provider errors, invalid model responses and exhausted budgets remain failures.
- All rows included in JSON output; no best-of-N selection.

Seeds vary amounts, regions and record counts. Repeating three seeds does not turn
ten fault families into thirty independently designed tasks. Do not compute
confidence intervals as if they did.

## Metrics

**Pass rate** is `(verified recoveries + correct read-only escalations) / episodes`.
The report separately includes:

- Resolved / resolvable episodes.
- Appropriate escalations.
- False success claims: the agent says resolved but the checker rejects it.
- Episodes with duplicate records.
- Tool calls, median wall time and provider-reported input/output token counts.
- Execution errors.

Wall time includes local model loading, inference, queueing and database actions.
Rate-limit waits advance a virtual clock and do not represent production latency.
No API cost estimate is attached to local inference.

## Baselines

`reference` is a deterministic policy written for this runbook. It is useful for
regression testing the environment and establishing a known successful trajectory.
It is not a learned agent.

`naive` intentionally retries append operations and trusts completion status. It
illustrates failure modes; beating it is not evidence of superiority over a strong
LLM baseline.

`ollama` executes genuine local inference with no rule-policy fallback. A useful
next comparison is another model or prompt on the same fixed suite, with unchanged
verifier semantics.

## Reproduce

```bash
python -m pip install -e ".[dev]" -c constraints.txt
pytest -q
resolvelab eval --policies naive reference --seeds 42 43 44 \
  --require-policy reference --output artifacts/offline-evaluation.json
ollama pull qwen3:4b
resolvelab eval --policies ollama --seeds 42 \
  --output artifacts/local-model-evaluation.json
```

On PowerShell, use a single line instead of the shell line-continuation backslashes.
Inspect `artifacts/RESULTS.md` for the measured release run and its limitations.
The CI workflow validates offline policies; it does not silently substitute a
mock for local-model evaluation.

## Train/evaluation separation

No model has been trained in v0.1. Exported traces are marked
`training_eligible: false`. Before training, define disjoint task families or
environment templates, label provenance, freeze the held-out set and review
trajectories for correctness. Public benchmark traces must not be mixed into a
claimed held-out evaluation. See the [roadmap](roadmap.md).
