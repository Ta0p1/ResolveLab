"""Publish portable evidence from a completed experiment; never synthesize model scores."""

import hashlib
import json
from pathlib import Path

from resolvelab.benchmark import digest, load_manifest
from resolvelab.experiments import compare
from resolvelab.store import dumps
from resolvelab.training import file_hash

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def main():
    output = ROOT / "artifacts/v0.2"
    training = read(ROOT / ".local/sft-v1/training.json")
    assert training["status"] == "completed"
    manifest = load_manifest(ROOT / "benchmarks/composition-v1.json")
    assert training["manifest_sha256"] == digest(manifest)
    base, sft = [read(output / f"{p}-test.json") for p in ("base", "sft")]
    comparison = compare(base, sft)
    control_base, control_sft = [read(output / f"{p}-format-test.json") for p in ("base", "sft")]
    control_comparison = compare(control_base, control_sft)
    control = {"base": control_base, "sft": control_sft, "comparison": control_comparison}
    selected = min(training["epochs"], key=lambda e: e["dev_loss"])
    assert training["selected_checkpoint"] == selected["checkpoint"]
    checkpoint = ROOT / ".local/sft-v1" / selected["checkpoint"]
    assert file_hash(checkpoint / "adapter_model.safetensors") == sft["adapter_sha256"]
    training["portable_data_sha256"] = {}
    for split in ("train", "dev"):
        source = ROOT / ".local/sft-data" / f"{split}.jsonl"
        assert file_hash(source) == training["data_sha256"][split], "Training data changed after launch"
        portable = source.read_text(encoding="utf-8")
        (output / "data").mkdir(exist_ok=True)
        (output / "data" / f"{split}.jsonl").write_text(portable, encoding="utf-8", newline="\n")
        training["portable_data_sha256"][split] = hashlib.sha256(portable.encode()).hexdigest()
    provenance = read(ROOT / ".local/sft-data/provenance.json")
    for split in ("train", "dev"):
        assert training["portable_data_sha256"][split] == provenance["splits"][split]["sha256"]
    write(output / "data/provenance.json", provenance)
    write(output / "training.json", training)
    write(output / "comparison.json", comparison)
    write(output / "format-comparison.json", control_comparison)
    write(
        ROOT / "src/resolvelab/static/experiment.json",
        {
            "comparison": comparison,
            "training": training,
            "manifest": manifest,
            "base": base,
            "sft": sft,
            "format_control": control,
        },
    )
    a, b = comparison["base"][0], comparison["sft"][0]
    c, d = control_comparison["base"][0], control_comparison["sft"][0]
    interval = comparison["template_bootstrap_95_interval"]
    text = f"""# ResolveLab v0.2: local post-training experiment

With a parser accepting one enclosing JSON code block: **{c["passed"]}/{c["episodes"]} base → {d["passed"]}/{d["episodes"]} LoRA**.
This control was added after observing test format failures, so it is **exploratory**.
Same Qwen3-0.6B revision, prompt, JSON protocol, greedy decoding and 18-action budget.
This is synthetic composition generalization in one service, with one training seed.

The pre-specified strict parser gave {a["passed"]}/{a["episodes"]} → {b["passed"]}/{b["episodes"]},
but every base episode failed at its first fenced JSON response, before executing
any tool. That contrast is dominated by **format compliance** and must not be
presented as a pure recovery-reasoning improvement. We retain it and report the
fence-only control rather than replacing the original denominator.

The fence-tolerant base also failed all 24 episodes: it read the runbook, then
returned malformed JSON for an unsupported completion. Thus the format control
does **not** remove the protocol confound. All base episodes share these initial
observations; they are not 24 independent reasoning failures. The supported claim
is successful deployment of the adapted policy on these tasks, not an isolated
gain in planning or general intelligence. Constrained decoding and a stronger
baseline on a fresh holdout are the next experiments.

| Policy | Pass | Writable tasks resolved | Correct escalation | False success | Errors | Median seconds |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3-0.6B base | {a["passed"]}/{a["episodes"]} | {a["resolved"]}/{a["resolvable_episodes"]} | {a["escalations"]} | {a["false_successes"]} | {a["errors"]} | {a["median_seconds"]:.2f} |
| Same base + LoRA | {b["passed"]}/{b["episodes"]} | {b["resolved"]}/{b["resolvable_episodes"]} | {b["escalations"]} | {b["false_successes"]} | {b["errors"]} | {b["median_seconds"]:.2f} |
| Base, fence-tolerant control | {c["passed"]}/{c["episodes"]} | {c["resolved"]}/{c["resolvable_episodes"]} | {c["escalations"]} | {c["false_successes"]} | {c["errors"]} | {c["median_seconds"]:.2f} |
| LoRA, fence-tolerant control | {d["passed"]}/{d["episodes"]} | {d["resolved"]}/{d["resolvable_episodes"]} | {d["escalations"]} | {d["false_successes"]} | {d["errors"]} | {d["median_seconds"]:.2f} |

Fence-tolerant paired outcomes: {control_comparison["wins"]} wins,
{control_comparison["regressions"]} regressions, {control_comparison["ties"]} ties.
No weights, prompts, task definitions or budgets changed for the control; only
one complete outer code block can be removed. Prose extraction, invalid-schema
repair and action substitution remain disallowed. This addresses one observed
confound; it is not a fresh confirmatory holdout.

Strict-parser paired outcomes: {comparison["wins"]} wins, {comparison["regressions"]} regressions, {comparison["ties"]} ties.
Pass-rate change: {comparison["pass_rate_delta"] * 100:+.1f} percentage points.
Exploratory 95% template-bootstrap interval: [{interval[0] * 100:.1f}, {interval[1] * 100:.1f}] points;
only eight template clusters. Seeds within a template are correlated. This interval
does not include training variance or uncertainty from other tasks and domains.

## Training evidence

- 72 training episodes / 528 next actions; 8 dev episodes / 62 next actions.
- {training["trainable_parameters"]:,} LoRA parameters; {training["config"]["epochs"]} epochs,
  {len(training["steps"])} optimizer steps, seed {training["config"]["seed"]}.
- {training["wall_seconds"] / 60:.2f} minutes on {training["hardware"]};
  peak allocated GPU memory {training["peak_allocated_gib"]:.2f} GiB.
- Selected **{training["selected_checkpoint"]}** by minimum dev action-token loss,
  before running held-out model inference. No test-based checkpoint selection.
- Verified scripted demonstrations; no larger-model teacher or RL.

## Per-template outcomes

| Fault composition | Strict base | Strict LoRA | Fence control base | Fence control LoRA |
|---|---:|---:|---:|---:|
"""
    for template in manifest["splits"]["test"]["templates"]:
        before = [r for r in base["rows"] if r["scenario"] == template["id"]]
        after = [r for r in sft["rows"] if r["scenario"] == template["id"]]
        cb = [r for r in control_base["rows"] if r["scenario"] == template["id"]]
        cs = [r for r in control_sft["rows"] if r["scenario"] == template["id"]]
        counts = " | ".join(
            f"{sum(r['verdict']['passed'] for r in group)}/{len(group)}"
            for group in (before, after, cb, cs)
        )
        text += f"| {' + '.join(template['faults'])} | {counts} |\n"
    text += """
## Audit and reproduce

[`base-test.json`](base-test.json), [`sft-test.json`](sft-test.json) and the adjacent
trace directories retain every episode. The `*-format-test.json` files and their
trace directories retain both sides of the parser control. [`training.json`](training.json) includes
per-step losses, dependencies, hashes and memory. [`data/`](data/) contains the
portable train/dev JSONL and provenance. The old 4B development baseline remains
in [`../RESULTS.md`](../RESULTS.md), with its original failure intact.

```bash
python scripts/verify_experiment.py
```

This checks split membership, selected weight hash, paired metrics and every
published test trajectory by executing its tools again against a fresh database.
It needs no model or GPU. The [protocol](../../docs/post-training.md) gives full
training and evaluation commands, assumptions and limits.

The [partial-commit regression](partial-recovery.json) separately records 3/3
Qwen3-4B recoveries after a bounded inference retry. That retry permits more
generated tokens; it is not a matched model-size or cost comparison with SFT.

These numbers do not establish external adoption, production reliability, unseen
tool capability or superiority over a strong general-purpose agent. The test set
is now public; subsequent tuning requires a new holdout.
"""
    (output / "RESULTS.md").write_text(text, encoding="utf-8", newline="\n")
    print(dumps({"comparison": comparison, "selected_checkpoint": str(checkpoint.relative_to(ROOT))}))


if __name__ == "__main__":
    main()
