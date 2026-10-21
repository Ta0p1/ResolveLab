# Resume and project description

Use these only for the implementation present in the repository.
GitHub: <https://github.com/Ta0p1/ResolveLab>

**ResolveLab — Agent Recovery, Evaluation & Post-Training**

Python · PyTorch · PEFT/LoRA · FastAPI · SQLite · Ollama · Qwen3 · Pytest

- Built a local tool-using support-agent workbench with nine typed tools and ten
  fault scenarios, including schema drift, ambiguous commits, partial writes,
  rate limits and permission-restricted recovery.
- Implemented transactional idempotency receipts, durable execution traces and
  restart recovery; independently verified record-level outcomes to detect
  duplicates, corrupted payloads and unsupported success claims.
- Built an action-only LoRA training pipeline for Qwen3-0.6B using 528 executable-verified
  expert actions; froze disjoint train/dev/test fault compositions and selected
  checkpoints by development loss before paired outcome evaluation.
- Made model claims auditable with source/data/weight hashes and GPU-free replay
  of all published test tool trajectories against fresh databases.

Current training results are in `artifacts/v0.2/RESULTS.md`; the historical baseline
is in `artifacts/RESULTS.md`. When including a number, specify the relevant
**synthetic composition holdout** or **development suite** and the denominator.
Do not describe scripted reference results as LLM accuracy.

Optional measured-results bullet:

- Trained a 5.05M-parameter LoRA adapter for Qwen3-0.6B on 528 verified expert
  actions; achieved 21 verified recoveries and 3 correct escalations on 24 frozen
  synthetic fault-composition tests, with complete executable trace audits.

Do not turn the base model's 0/24 into a claim of pure reasoning improvement:
its failures are dominated by protocol errors, including in the exploratory
fence-tolerant control. The report makes this confound explicit.

Historical v0.1 alternative:

- Evaluated local Qwen3 4B across 10 public synthetic recovery scenarios, observing
  8 verified recoveries and 1 correct escalation with zero false-success claims;
  retained the failed partial-commit trajectory for targeted error analysis.

## Thirty-second introduction

> ResolveLab is a local agent engineering project focused on whether an agent
> actually fixes a failed workflow. I built a stateful sync sandbox with faults
> such as a committed write whose acknowledgement is lost. The model chooses
> typed tool actions, while a separate checker evaluates the final database.
> I then trained a small LoRA policy on verified expert actions and compared it
> with the same base model on frozen fault combinations. The workbench exposes
> the outcomes and failures, and another developer can replay the traces without
> a GPU. My next step is testing transfer to a second service and new fault families.

## Claims that are not established

No production users, generalization to unseen tools/domains, quantified business
impact or superiority over a competitive general-purpose agent is claimed.
Repository stars are a visibility signal; the technical claims should remain
supported by code, tests and reproducible runs.
