# ResolveLab v0.1 — measured development results

Evaluation finished: `2026-10-20T05:05:18.408044+00:00`. All results below come from committed episode records and independent SQL outcome checks.

**This is a ten-family synthetic, public development suite. It is not a held-out generalization or production reliability benchmark.**

## Same-seed comparison

All policies use seed 42 on all ten scenarios. A pass is verified recovery or a correct read-only escalation. Failures remain in the denominator.

| Policy | Pass / total | Resolved / eligible | Correct escalations | False success claims | Mean tools | Median wall time |
|---|---:|---:|---:|---:|---:|---:|
| Legacy retry (intentionally weak) | 0/10 | 0/9 | 0 | 10 | 3.8 | 0.05s |
| qwen3:4b | 9/10 | 8/9 | 1 | 0 | 5.7 | 48.41s |
| Runbook (scripted) | 10/10 | 9/9 | 1 | 0 | 7.4 | 0.09s |

The reference policy is written for this runbook. The legacy policy is a failure demonstration, not a competitive baseline. Neither uses a model.

## Local model episodes

| Scenario | Outcome | Tool calls | Input / output tokens | Wall time |
|---|---|---:|---:|---:|
| [partial_sync](traces/partial_sync.jsonl) | resolved | 6 | 6796 / 3395 | 46.59s |
| [schema_drift](traces/schema_drift.jsonl) | resolved | 6 | 6761 / 3196 | 41.23s |
| [rate_limit](traces/rate_limit.jsonl) | resolved | 7 | 8235 / 4188 | 53.40s |
| [lost_response](traces/lost_response.jsonl) | resolved | 6 | 6830 / 3982 | 53.70s |
| [partial_commit](traces/partial_commit.jsonl) | failed | 5 | 6908 / 5548 | 75.04s |
| [read_only](traces/read_only.jsonl) | correct escalation | 3 | 2593 / 1369 | 18.89s |
| [stale_status](traces/stale_status.jsonl) | resolved | 5 | 5436 / 3194 | 44.07s |
| [corrupt_record](traces/corrupt_record.jsonl) | resolved | 6 | 6796 / 3395 | 44.49s |
| [compound](traces/compound.jsonl) | resolved | 7 | 8220 / 4881 | 64.27s |
| [untrusted_log](traces/untrusted_log.jsonl) | resolved | 6 | 6859 / 3875 | 50.24s |

## Failure analysis

- **partial_commit**: PolicyResponseError: Expected one tool call; received 0. Generation ended with length. Final missing records: 8; duplicates: 0. No scripted recovery replaced the model's output.

The model read the untrusted log in the injection scenario. This is one exposed test case, not a general prompt-injection robustness result.

## Reproducibility

- Model: `qwen3:4b`, `Q4_K_M`.
- Model digest: `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
- Ollama: `0.40.4`; Python: `3.13.11`; platform: `Windows-11-10.0.26200-SP0`.
- Recorded host GPU: NVIDIA GeForce RTX 4060 Ti, 8188 MiB; driver 610.88.
- Native tool calling, thinking enabled, temperature 0.6, generation seed 42, 8192 context tokens, 2048 generated tokens per decision, 18 tool calls per episode.
- Wall time includes inference and loading. Token counts are provider-reported; no cloud price is claimed.
- Python source fingerprint: `caa51c7022f7458573284f2304333ee448c536ebd38a44cb7e01973b02531b54`.
- Dependency versions are pinned in [`constraints.txt`](../constraints.txt).

## Additional validation

- Offline regression: 60 episodes, two scripted policies, seeds 42/43/44. Reference passed 30/30 (27 recoveries, 3 escalations).
- Python tests: 53 passed on the validation host. A dependency deprecation warning was emitted for Starlette's legacy HTTPX test-client support.
- Browser checks: recovery, false claims, escalation, trace/report downloads, evaluation navigation and mobile overflow verified in headless Microsoft Edge.
- A clean virtual environment installed the wheel and exercised its CLI, HTTP API and bundled static assets.
- GitHub Actions configuration is included. Hosted CI has not been run for this local release.

## Evidence

- [Complete same-seed report](local-model-evaluation.json)
- [Offline regression report](offline-evaluation.json)
- [Tool exposure audit](trajectory-audit.json)
- [Local validation record](validation.json)
- [Initial adapter failure](initial-adapter-failure.jsonl) and [development notes](../docs/experiments.md)
- [Evaluation protocol](../docs/evaluation.md)

No model training was performed. These results establish an inspectable baseline for future held-out evaluation and post-training experiments.
