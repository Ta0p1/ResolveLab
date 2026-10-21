# Post-training protocol: composition-v1

ResolveLab trains a local recovery policy and evaluates **executed outcomes**.
The experiment is supervised imitation of a scripted runbook expert. It is not
RL, distillation from a larger language model, or a production incident dataset.

## Protocol frozen before training

The manifest is [`benchmarks/composition-v1.json`](../benchmarks/composition-v1.json).
Its canonical JSON SHA-256 is
`f7811a869f67e5374ee8333e1359456de856c078c306b9ada5ea30efdcf1076c`.
The initial experiment code and configuration were committed as `ad7f12f` before
training started. Subsequent report validation and presentation changes retain
separate source fingerprints in each artifact.

| Split | Fault compositions | Seeds per composition | Episodes | Use |
|---|---:|---:|---:|---|
| Train | 9 | 8 | 72 | 528 verified next-action examples |
| Development | 4 | 2 | 8 | 62 actions; checkpoint selection by action-token loss |
| Test | 8 | 3 | 24 | Base/SFT outcome evaluation after checkpoint selection |

Training contains the normal case and individual faults. Development and test
contain disjoint combinations of those faults. Composition signatures are sorted
before checking overlap; changing their order cannot bypass the split check.
IDs and seeds must also be disjoint. The old ten-case suite remains a public
regression suite, and is not described as held-out evidence.

This tests **new compositions within the same service**. It does not test new
tools, unseen fault primitives, new business domains or realistic customer prose.
There are only eight test templates; three record seeds do not make three new
task families. The test manifest becomes public with this release. Further tuning
against these outcomes must call it development data and introduce a new holdout.

## Data and leakage boundaries

`scripts/post_train.py collect` executes the scripted reference on train/dev
episodes only. An episode is accepted only if the independent SQL verifier passes
it. Prefixes contain the task, public tool definitions and preceding tool results;
they exclude fault flags, template IDs, split labels, final verdicts and internal
mutation metadata. The next expert action is the supervised target.

`validate_training_rows` rejects foreign manifest hashes, wrong-split episodes,
duplicate steps, unverified trajectories and test-as-training requests. The
collector normalizes non-semantic escalation ticket IDs. Files use canonical
UTF-8/LF serialization; their hashes and accepted/rejected episode counts are
recorded in `provenance.json`. The first run was collected on Windows with CRLF;
its training report preserves those original byte hashes. Published portable
copies use LF and match the collector's canonical hashes. Record content is
identical; both hash conventions are documented rather than silently rewritten.

Development actions never contribute gradients. No model-generated test failure
is added to training. The reference policy uses observations, rather than reading
the scenario's fault flags. It provides a task-specific expert and a simulator
sanity check, not a competitive model baseline.

## Model, optimization and selection

The base is [Qwen/Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B), pinned to
revision `c1899de289a04d12100db370d81485cdf75e47ca` (Apache-2.0). The implementation
uses the model's chat template with `enable_thinking=False` and a JSON action
protocol. Both the base and trained policies use exactly the same prompt and
decoder. Neither receives a rule-policy fallback or automatic JSON repair.

[`benchmarks/sft-v1.json`](../benchmarks/sft-v1.json) fixes seed 3407, three epochs,
LoRA rank 8 / alpha 16 / dropout 0.05, all seven attention/MLP projection types,
AdamW at 2e-4, effective batch size 8, ten warm-up steps and cosine decay. BF16
training uses gradient checkpointing and clips the gradient norm at 1.0.
Only 5,046,272 adapter parameters are trainable.

Loss covers only next-action tokens and the end-of-turn token. Tool observations
and other prefix tokens have no direct language-model loss. Computing vocabulary
logits only at action positions reduces memory; a numerical test checks that the
loss and gradients match a full causal LM forward pass with prefix labels masked.
Over-length examples fail explicitly rather than silently losing the task.

Checkpoint selection is the **lowest token-weighted development action loss**
among epoch-end checkpoints, specified before test inference. Selection does not
use the test pass rate. Lower training loss alone is not a recovery improvement.

Implementation references: [Qwen model card](https://huggingface.co/Qwen/Qwen3-0.6B),
[PEFT quick tour](https://huggingface.co/docs/peft/quicktour),
[PyTorch CUDA installation](https://pytorch.org/get-started/locally/).

## Reproduce locally

The recorded training runs in Ubuntu under WSL on an RTX 4060 Ti with 8GB VRAM.
Use a dedicated environment. The ordinary workbench needs no training packages.

```bash
python3 -m venv .train-venv
source .train-venv/bin/activate
pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu126
pip install -r requirements-training.txt
pip install -e ".[dev]"
python scripts/post_train.py collect
python scripts/post_train.py train --output .local/sft-v1
```

Training refuses to overwrite an experiment directory. `training.json` contains
every optimizer step, epoch losses, selected checkpoint, weight hashes, versions,
memory and wall time. Choose its `selected_checkpoint` for the commands below.

```bash
python scripts/post_train.py eval --split test \
  --output .local/base-test.json --data .local/paired-eval
python scripts/post_train.py eval --split test \
  --adapter .local/sft-v1/SELECTED_CHECKPOINT \
  --output .local/sft-test.json --data .local/paired-eval
python scripts/post_train.py compare \
  --base-report .local/base-test.json --sft-report .local/sft-test.json \
  --output .local/comparison.json
```

Use `--split dev` to inspect development outcomes. Use `--reference` for a
GPU-free environment check. An interrupted evaluation can resume with `--resume`
only when code, config, model adapter, split and manifest match. Completed reports
cannot be overwritten. Raw traces accompany each report, including failures.

## Fair comparison and interpretation

Both policies have 18 tool actions, 4,096 context tokens and at most 192 generated
tokens per action. They use greedy decoding, BF16, SDPA and zero inference retries.
They see the same records, permissions, runbook and tools. Model-loading time is
outside episode latency; actual tool execution and inference are inside it.
Malformed output, context overflow and budget exhaustion remain failures in the
denominator. Correct read-only escalation counts as a pass and is reported
separately from writable-task resolution.

Reports include false claims, duplicates, protocol errors, invalid tool arguments,
latency, tokens, per-template results and all raw trajectories. Paired wins,
regressions and ties are computed on identical `(template, seed)` cases. An
exploratory bootstrap resamples templates rather than treating correlated seeds
as independent. A single training seed cannot estimate training variance.

The 4B Ollama regression results use a different inference protocol and budget.
They are retained as operational evidence, not as a matched model-size ablation.
No conclusion about superiority over general-purpose agent frameworks follows.

## Operational repair: missing action after truncation

The v0.1 partial-commit failure reached 2,048 output tokens without a function
call. v0.2 retries **inference only** once, allowing 4,096 tokens with a short
protocol reminder. It does not replay a write or select a tool through rules.
All observed tokens from both attempts remain in usage, including retry failures.
Multiple calls or invalid schemas still fail; retry exhaustion is terminal.
The original failure is retained in `artifacts/traces/`.

Three real Qwen3-4B partial-commit episodes (seeds 42, 73, 101) recovered under this
policy, with zero duplicates and false claims. This is a targeted regression
check at a larger worst-case inference budget, not a free accuracy gain. HTTP
timeouts after a lost provider response can have unobservable token usage; the
report records only usage returned by the provider.
