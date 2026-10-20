# Resume and project description

Use these only for the implementation present in the repository. Add the public
GitHub URL once the project has actually been published.

**ResolveLab — Local Agent Recovery & Evaluation Platform**

Python · FastAPI · SQLite · Ollama · Qwen3 · Pytest

- Built a local tool-using support-agent workbench with nine typed tools and ten
  fault scenarios, including schema drift, ambiguous commits, partial writes,
  rate limits and permission-restricted recovery.
- Implemented transactional idempotency receipts, durable execution traces and
  restart recovery; independently verified record-level outcomes to detect
  duplicates, corrupted payloads and unsupported success claims.
- Integrated local Qwen inference and a reproducible evaluation harness reporting
  verified recovery, correct escalation, false-success rate, token usage and latency.

The measured release results are in `artifacts/RESULTS.md`. When including a
number, say **synthetic development scenarios** and state the denominator.
Do not describe scripted reference results as LLM accuracy.

Optional measured-results bullet:

- Evaluated local Qwen3 4B across 10 public synthetic recovery scenarios, observing
  8 verified recoveries and 1 correct escalation with zero false-success claims;
  retained the failed partial-commit trajectory for targeted error analysis.

## Thirty-second introduction

> ResolveLab is a local agent engineering project focused on whether an agent
> actually fixes a failed workflow. I built a stateful sync sandbox with faults
> such as a committed write whose acknowledgement is lost. The model chooses
> typed tool actions, while a separate checker evaluates the final database.
> The workbench exposes failures, traces and reproducible measurements. The next
> phase is a held-out evaluation split and small-model post-training.

## Claims that are not established

No production users, trained model, held-out generalization result, quantified
business impact or superiority over a competitive agent baseline is claimed.
Repository stars are a visibility signal; the technical claims should remain
supported by code, tests and reproducible runs.
