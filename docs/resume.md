# Resume and project description

Use these only for the implementation present in the repository.
GitHub: <https://github.com/Ta0p1/ResolveLab>

**ResolveLab — Agent Recovery, Evaluation & Post-Training**

Python · PyTorch · PEFT/LoRA · FastAPI · HTTP/ETag · SQLite · Constrained decoding · Pytest

## v0.4 bullets (quote these, with their scope)

- Found a shortcut in my own fine-tuned agent with a counterfactual: holding records fixed,
  the v0.3 Qwen3-0.6B LoRA adapters solved 54/54 later-page lookups under the published
  in-context demo and 0/54 when only the demo's layout changed; rebuilt the benchmark with
  288 independent records, declared position/decoy/wording factors and held-out wording.
- Ran a pre-registered DAgger study with a size-matched behaviour-cloning control and a
  replay-verified, off-policy-safe teacher: 98.3% vs 90.8% success on a locked 120-episode
  synthetic HTTP holdout (+7.5 pp, 95% CI [1.9, 13.3] over three training seeds and records),
  removing a compounding ETag-copy failure that extra expert data did not fix.
- Kept the evidence executable: hash-locked inputs and adapters, a GPU-free verifier that
  re-derives every DAgger label and replays all 1,920 test episodes over real HTTP.

Scope to say out loud: synthetic, process-local service with a known contract; held-out
compositions, records and wording, not new tools or real incidents; one model family, three
seeds, one DAgger iteration; small local baselines only.

## Current v0.3 bullets

- Engineered an agent recovery lab spanning SQLite sync and a real HTTP ticket
  adapter, with pagination, optimistic concurrency, idempotency and permission
  revocation; independently graded final state, unsafe writes and false success.
- Built a controlled post-training study with static JSON Schema constrained
  baselines, a larger 1.7B model, one-shot prompting and three LoRA training seeds;
  froze 30 test episodes across 10 fault compositions before model runs and selected
  checkpoints on development loss.
- Made results auditable through exact data/prompt/weight hashes, raw HTTP traces
  and GPU-free replay of all 180 published HTTP test episodes.

<!-- HTTP_RESUME_RESULT_START -->

- Improved Qwen3-0.6B task success from 0.0% to 77.8% mean (66.7–100.0% across three LoRA seeds) on a registered 30-episode, 10-composition synthetic HTTP recovery holdout; used identical one-shot prompts and schema-constrained decoding, with independent state verification and complete trace replay.

Both baseline and adapted arms had 100% schema-valid calls; this comparison controls the format-rejection confound.
<!-- HTTP_RESUME_RESULT_END -->

> **Do not lead with the v0.3 number.** The [v0.3 review](v0.3-review.md) shows the 30
> episodes are three records, the matched base never reached a fault, and a counterfactual
> shows the adapters copy the demo's layout. If you cite it, cite it as the finding you
> then took apart; the v0.4 study is the result to quote.

## Historical v0.2 bullets

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

Historical v0.2 training results are in `artifacts/v0.2/RESULTS.md`; the original baseline
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
> I added a second service over real HTTP and compared small-model LoRA policies
> with schema-constrained baselines under the same prompts and budgets. The grader
> checks the actual records and write history, so valid JSON and convincing success
> claims are not enough. The workbench exposes every failure, and another developer
> can replay the actions without a GPU. The current results are limited to known
> contracts and held-out fault combinations, not production incidents.

## Claims that are not established

No production users, generalization to unseen tools/domains, quantified business
impact or superiority over a competitive general-purpose agent is claimed.
Repository stars are a visibility signal; the technical claims should remain
supported by code, tests and reproducible runs.
