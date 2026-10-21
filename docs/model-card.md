---
base_model: Qwen/Qwen3-0.6B
library_name: peft
license: apache-2.0
tags:
  - lora
  - tool-calling
  - synthetic-data
---

# ResolveLab Qwen3-0.6B LoRA, experiment v1

This adapter learns the ResolveLab JSON action protocol and scripted recovery
policy. It is intended for reproducing the synthetic sync-service experiment.
It is not a general support assistant or a production operator.

Base revision: `c1899de289a04d12100db370d81485cdf75e47ca`.
Selected adapter: `epoch-2`, SHA-256
`e99f1065100c969f54e00ad3c4c0ea1cc2e9b4e32524fc194bb3bfb8b78bc8b5`.
The underlying Qwen model is Apache-2.0; source code and synthetic records in
ResolveLab use the repository's MIT license. No base-model weights are bundled.

## Training

72 synthetic expert episodes, 528 next-action examples, 9 individual-fault
templates. LoRA rank 8 / alpha 16 on attention and MLP projections, 5,046,272
trainable parameters. Three BF16 epochs, 198 optimizer steps, seed 3407, AdamW
2e-4, effective batch 8. The best checkpoint was selected by development
action-token cross-entropy over 8 disjoint composition tasks. Test outcomes did
not select the weights. Training took 959.8 seconds on a local RTX 4060 Ti;
peak PyTorch-allocated memory was 1.65 GiB (not total process/device memory).

The supervised loss excludes prompt and tool-observation tokens. There is no
larger-model teacher, human preference data or reinforcement learning. All expert
trajectories passed executable final-state checks; they are not manually authored
real customer incidents. See [the full protocol](post-training.md).

## Evaluation and limitations

The selected policy passed 24/24 frozen composition tests with the pre-specified
strict parser: 21 writable recoveries and 3 appropriate read-only escalations.
The base model failed on output formatting before acting. A fence-tolerant control
was added after this discovery and is explicitly exploratory. Base failures
remain dominated by protocol errors, so the comparison cannot establish an
isolated improvement in planning or reasoning. Full results and every trajectory
are in [`artifacts/v0.2`](../artifacts/v0.2/RESULTS.md).

The environment has one adapter, a fixed runbook and eight test compositions of
known fault primitives. Only one training seed was run. Successful synthetic
rollouts do not establish external-service reliability, unseen-tool capability,
or robustness to broad prompt injection. The public test set must not be reused
for future tuning while described as held out.

## Load and evaluate

The adapter remains in `.local/sft-v1/epoch-2` on the machine that performed the
experiment. Reproduce it from the pinned configuration and published synthetic
data using [post-training.md](post-training.md). Large weights are excluded from
Git; the published weight hash makes local checkpoints identifiable.

```bash
python scripts/post_train.py eval --split test \
  --adapter .local/sft-v1/epoch-2 \
  --output .local/reproduced-sft-test.json --data .local/reproduced-eval
```

Use the same base revision, tokenizer template (`enable_thinking=False`), prompt,
JSON protocol, 192-token generation limit and 18-action budget. The workbench's
Post-training page displays measured evidence; live HF inference currently uses
the CLI. Preserve the server's permission checks and independent verifier.
