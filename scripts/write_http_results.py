"""Derive human-readable claims from the completed, audited result bundle."""

import json
import statistics
from collections import Counter
from pathlib import Path

from resolvelab.httpdesk.service import DeskState

root = Path(__file__).resolve().parents[1]
bundle = root / "artifacts/v0.3"


def read(name):
    return json.loads((bundle / f"{name}.json").read_text(encoding="utf-8"))


names = ["base-test", "large-test", "sft-3407-test", "sft-42-test", "sft-2026-test"]
labels = ["Qwen3-0.6B base", "Qwen3-1.7B base", "0.6B LoRA / 3407", "0.6B LoRA / 42", "0.6B LoRA / 2026"]
reports = {name: read(name) for name in names}
control_report = read("ollama-4b-test")
control = control_report["summary"]
trace_cache = {}


def read_trace(name, row):
    key = (name, row["trace"])
    if key not in trace_cache:
        trace_cache[key] = json.loads((bundle / name / row["trace"]).read_text(encoding="utf-8"))
    return trace_cache[key]


def transport_failures(name, row):
    return sum(o["result"].get("status") == 0 for o in read_trace(name, row)["observations"])


assert all(r["status"] == "completed" and len(r["rows"]) == 30 for r in reports.values())
table = [
    "| Model / seed | Passed | Resolved | Escalated | Valid calls | Unsafe writes | False success | Redundant writes | Median seconds |",
    "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
]
short = ["| Policy | Task success | Schema-valid calls | False success |", "|---|---:|---:|---:|"]
for name, label in zip(names, labels, strict=True):
    s = reports[name]["summary"]
    table.append(
        f"| {label} | {s['passed']}/30 | {s['resolved_passed']} | {s['escalated_passed']} | {100 * s['schema_valid_rate']:.1f}% | {s['unsafe_mutations']} | {s['false_successes']} | {s['redundant_commits']} | {s['median_seconds']:.2f} |"
    )
    short.append(
        f"| {label} | {s['passed']}/30 | {100 * s['schema_valid_rate']:.1f}% | {s['false_successes']} |"
    )
trained = [reports[n]["summary"] for n in names[2:]]
rates = [s["success_rate"] for s in trained]
base = reports["base-test"]["summary"]
all_valid = all(r["summary"]["schema_valid_rate"] == 1 for r in reports.values())
text = [
    "# CaseDesk HTTP study — v0.3",
    "",
    "Registered synthetic composition holdout; real local inference and real HTTP transport.",
    "",
    f"Across three registered LoRA seeds, task success ranged from **{min(rates) * 100:.1f}% to {max(rates) * 100:.1f}%** "
    f"(mean {statistics.mean(rates) * 100:.1f}%, sample SD {statistics.stdev(rates) * 100:.1f} percentage points). "
    f"The matched 0.6B baseline passed **{base['passed']}/30**; the larger 1.7B baseline passed "
    f"**{reports['large-test']['summary']['passed']}/30**.",
    "",
    (
        "Every primary model arm had **100% schema-valid calls**. Thus the observed task-success differences are not attributable to rejected JSON or invalid tool schemas."
        if all_valid
        else "Call validity is measured separately below; do not attribute all success differences to semantic decisions."
    ),
    "",
    *table,
    "",
    "Pass includes verified resolution or a justified escalation after an actual target-ticket 403. "
    "Unsafe writes count committed wrong-record/incorrect-value mutations; redundant writes count commits whose prior priority/status already matched the request. "
    "A redundant write to the wrong record also counts as unsafe. "
    "HTTP errors such as 412/429/502 are expected task observations, not automatic failures.",
    "",
    "## Supplementary 4B control",
    "",
    f"Qwen3-4B Q4_K_M through Ollama passed **{control['passed']}/30**, with {100 * control['schema_valid_rate']:.1f}% "
    f"schema-valid calls, {control['unsafe_mutations']} unsafe writes, {control['false_successes']} false success claims "
    f"and {control['median_seconds']:.2f}s median episode time. [Raw report](ollama-4b-test.json).",
    "",
    "This separately registered control uses the same base contract, example, schema and nominal action/token limits, "
    "with the original prompt selected on development tasks. Quantization, inference backend, "
    "chat template details and grammar engine differ, so it is not a matched "
    "training comparison. Its 30 episodes are additional to the primary 150. Latency retains model-load time; "
    "a lower parameter count alone does not establish a speed or cost advantage.",
    "",
    "## Matched 0.6B comparisons",
    "",
    "| Training seed | Wins | Regressions | Ties | Gain (pp) | Template-bootstrap 95% interval (pp) | Wins with valid calls in both arms |",
    "|---|---:|---:|---:|---:|---|---:|",
]
before = {(r["template"], r["seed"]): r for r in reports["base-test"]["rows"]}
for seed in (3407, 42, 2026):
    comp = read(f"comparison-{seed}")
    clean_wins = sum(
        r["passed"]
        and not before[(r["template"], r["seed"])]["passed"]
        and r["schema_valid"] == r["decisions"]
        and before[(r["template"], r["seed"])]["schema_valid"]
        == before[(r["template"], r["seed"])]["decisions"]
        for r in reports[f"sft-{seed}-test"]["rows"]
    )
    lo, hi = comp["template_bootstrap_95ci"]
    text.append(
        f"| {seed} | {comp['wins']} | {comp['regressions']} | {comp['ties']} | {100 * comp['success_delta']:.1f} | [{100 * lo:.1f}, {100 * hi:.1f}] | {clean_wins} |"
    )
text += [
    "",
    "Intervals resample the 10 templates (10,000 bootstrap draws, seed 2026), not 30 supposedly independent incidents. "
    "The same three record seeds appear across templates. Shared fault mechanisms create further dependence; "
    "these descriptive intervals do not bound production reliability. The 1.7B model is a size control, not a paired training effect.",
    "",
    "## Failure accounting",
    "",
]
text += [
    "JSON Schema controls tool names, argument types and enum values. It does **not** guarantee "
    "that copied strings are valid HTTP header values or identify the correct record. "
    "The following post-hoc diagnostics retain all episodes in the primary denominator. "
    "Each episode receives one prioritized failure category; unsafe, redundant and false-success counters can overlap. "
    "Thus the false-success category alone is not the total number of false success claims.",
    "",
    "| Policy | Episodes with transport/header errors | Such failed calls | Failed episodes with valid calls and no transport/header error |",
    "|---|---:|---:|---:|",
]
for name, label in zip(names + ["ollama-4b-test"], labels + ["Supplementary 4B"], strict=True):
    report = control_report if name == "ollama-4b-test" else reports[name]
    counts = [transport_failures(name, row) for row in report["rows"]]
    remaining = sum(
        not row["passed"] and row["schema_valid"] == row["decisions"] and count == 0
        for row, count in zip(report["rows"], counts, strict=True)
    )
    text.append(f"| {label} | {sum(c > 0 for c in counts)} | {sum(counts)} | {remaining} |")
text += [
    "",
    "These remaining failures concern action selection, argument values or outcome verification; they do not by themselves isolate a general reasoning capability.",
    "",
]
for name, label in zip(names, labels, strict=True):
    failed = [r for r in reports[name]["rows"] if not r["passed"]]
    counts = Counter(r["error"] or r["failure_category"] for r in failed)
    text.append(
        f"- **{label}:** "
        + (
            ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
            if failed
            else "no failed episodes in this test."
        )
        + (f" [Example raw failure]({name}/{failed[0]['trace']})." if failed else "")
    )
control_failures = [r for r in control_report["rows"] if not r["passed"]]
control_counts = Counter(r["error"] or r["failure_category"] for r in control_failures)
text += [
    "- **Supplementary 4B control:** "
    + (
        ", ".join(f"{k}: {v}" for k, v in sorted(control_counts.items()))
        if control_counts
        else "no failed episodes"
    )
    + ".",
    "",
    "## One compound case, without changing the denominator",
    "",
    "The following view uses `test_conflict_rate_lost / 6301`: the triple-fault template "
    "and its first registered record seed. LoRA seed 3407 is the first registered training seed, "
    "not the best-scoring seed. All other cases and training seeds remain in the tables and raw bundle.",
    "",
]
for name, label in [
    ("base-test", "0.6B baseline"),
    ("large-test", "1.7B baseline"),
    ("sft-3407-test", "0.6B LoRA / 3407"),
    ("ollama-4b-test", "Supplementary 4B control"),
]:
    filename = "test_conflict_rate_lost-6301.json"
    trace = json.loads((bundle / name / filename).read_text(encoding="utf-8"))
    sequence = " → ".join(
        f"`{o['name']}({o['result'].get('status', o['result'].get('finished', 'end'))})`"
        for o in trace["observations"]
    )
    verdict = trace["verdict"]
    text += [
        f"**{label}: {'PASS' if verdict['passed'] else 'FAIL'}** — {verdict['failure_category'] or verdict['claim']}; "
        f"{verdict['commits']} committed writes. [Exact arguments and state]({name}/{filename}).",
        "",
        sequence,
        "",
    ]
text += [
    "",
    "## Record-seed coverage (post-hoc diagnostic)",
    "",
    "| Record seed | Target index (zero-based) | 0.6B base | 1.7B base | LoRA 3407 | LoRA 42 | LoRA 2026 | 4B control |",
    "|---|---:|---:|---:|---:|---:|---:|---:|",
]
manifest = json.loads((root / "benchmarks/httpdesk-v1.json").read_text(encoding="utf-8"))
for seed in manifest["splits"]["test"]["seeds"]:
    state = DeskState([], seed)
    cells = []
    for report in [*reports.values(), control_report]:
        rows = [r for r in report["rows"] if r["seed"] == seed]
        cells.append(f"{sum(r['passed'] for r in rows)}/{len(rows)}")
    text.append(f"| {seed} | {list(state.tickets).index(state.target)} | " + " | ".join(cells) + " |")
positions = {}
for split, part in manifest["splits"].items():
    positions[split] = [
        list((state := DeskState([], seed)).tickets).index(state.target) for seed in part["seeds"]
    ]
text += [
    "",
    f"Target indices by split: train `{positions['train']}`, development `{positions['dev']}`, test `{positions['test']}`. "
    "This coverage audit was performed after test inference began, not used to change the locked data. "
    "The first-record target is absent from training/development. Repeated pagination on that record exposes "
    "a real coverage/generalization gap, despite successful development rollouts. Position is correlated "
    "with the other values in each seed, so this is a diagnostic hypothesis, not an isolated causal attribution.",
    "",
    "Template-bootstrap intervals above condition on these three record variants. If errors are shared "
    "across templates for one seed, those intervals can be artificially narrow or even degenerate; "
    "they do not capture record-distribution uncertainty. More independent records and a new holdout "
    "are needed before a reliability claim. The published test is not reused for training or model selection.",
    "",
    "## Inference resource accounting",
    "",
    "| Primary arm | Mean tool actions / episode | Total output tokens | Total input tokens |",
    "|---|---:|---:|---:|",
]
for name, label in zip(names, labels, strict=True):
    report = reports[name]
    summary = report["summary"]
    text.append(
        f"| {label} | {summary['mean_tools']:.2f} | {summary['output_tokens']} | "
        f"{sum(row['input_tokens'] for row in report['rows'])} |"
    )
text += [
    "",
    "Counts include failed episodes and repeated reads. A fast incorrect termination is not an efficient "
    "recovery. These unmerged PEFT rollouts and constrained HF decoding are not serving-throughput "
    "benchmarks; compare the full success/cost tradeoff. The supplementary Ollama backend reports "
    "cached/prefill counts differently, so its raw usage is retained without combining input-token totals.",
    "",
    "## Training and reproducibility",
    "",
    "| Seed | Selected checkpoint | Dev action loss | Training seconds | Peak allocated GiB |",
    "|---|---|---:|---:|---:|",
]
for seed in (3407, 42, 2026):
    t = read(f"training-{seed}")
    chosen = next(e for e in t["epochs"] if e["checkpoint"] == t["selected_checkpoint"])
    text.append(
        f"| {seed} | {chosen['checkpoint']} | {chosen['dev_loss']:.6f} | {t['wall_seconds']:.1f} | {t['peak_allocated_gib']:.2f} |"
    )
text += [
    "",
    "48 training episodes / 322 verified scripted actions; 8 development episodes / 58 actions. "
    "Action-only LoRA rank 8, 5,046,272 trainable parameters, BF16 on an RTX 4060 Ti 8GB. "
    "Three epochs per seed. All primary arms share the same training demonstration, prompt, static grammar, "
    "24-action limit, 192 generated tokens per action and 8192-token context. Greedy non-thinking decoding, no hidden retry or rule fallback.",
    "",
    "The manifest was committed before model runs (`7e5ffb4`). The [training lock](training-lock.json) and "
    "[test lock](test-lock.json) pin data, code, prompt/schema and selected adapters. "
    "Development-only prompt improvements preceded the test lock; see the amendment in the "
    "[registered protocol](../../docs/httpdesk-protocol.md). No test outcome was used to select a checkpoint or seed.",
    "",
    "Run `python scripts/verify_http_study.py` to check split membership, hashes, checkpoint selection, "
    "metrics and all 180 model episodes (150 primary + 30 supplementary) by executing recorded actions through fresh HTTP sockets. "
    "This audits environment outcomes, not exact model token regeneration on arbitrary hardware.",
    "",
    "## Limits",
    "",
    "- Synthetic process-local ticket backend; no real SaaS account, production users or restart-durable remote receipts.",
    "- Known API and fault primitives; held-out compositions are not unseen domains or zero-shot service transfer.",
    "- Fixed task wording and only three distinct test record seeds. No paraphrase-robustness claim; episode count is not a count of independent customer requests.",
    "- End-to-end gains include exact reference matching, argument copying and workflow following. A baseline that never reaches an injected HTTP fault does not isolate recovery reasoning for that fault.",
    "- Only three training seeds, one small fine-tuned model family and one training dataset. This does not establish general agent reasoning gains.",
    "- The one-shot, greedy non-thinking baselines are stronger than an unconstrained parser-only baseline, but are not frontier-agent or best-possible prompting comparisons.",
    "- Test tasks are now public. Further tuning requires a new holdout and a new experiment name.",
    "- Equal token/action budgets do not imply equal compute, latency or cost across model sizes.",
    "",
]
(bundle / "RESULTS.md").write_text("\n".join(text), encoding="utf-8", newline="\n")
for name in ("README.md", "README.zh-CN.md"):
    path = root / name
    content = path.read_text(encoding="utf-8")
    start, tail = content.split("<!-- HTTP_RESULTS_START -->", 1)
    _, end = tail.split("<!-- HTTP_RESULTS_END -->", 1)
    path.write_text(
        start
        + "<!-- HTTP_RESULTS_START -->\n\n"
        + "\n".join(short)
        + f"\n\nSupplementary Qwen3-4B Q4_K_M / Ollama: **{control['passed']}/30** passed, **{100 * control['schema_valid_rate']:.1f}%** schema-valid calls. Different quantization/backend; not a matched training effect.\n\n[Full results, paired intervals and failures](artifacts/v0.3/RESULTS.md).\n<!-- HTTP_RESULTS_END -->"
        + end,
        encoding="utf-8",
        newline="\n",
    )
path = root / "docs/resume.md"
content = path.read_text(encoding="utf-8")
start, tail = content.split("<!-- HTTP_RESUME_RESULT_START -->", 1)
_, end = tail.split("<!-- HTTP_RESUME_RESULT_END -->", 1)
bullet = (
    f"- Improved Qwen3-0.6B task success from {100 * base['success_rate']:.1f}% to {100 * statistics.mean(rates):.1f}% mean "
    f"({100 * min(rates):.1f}–{100 * max(rates):.1f}% across three LoRA seeds) on a registered 30-episode, "
    f"10-composition synthetic HTTP recovery holdout; "
    f"used identical one-shot prompts and schema-constrained decoding, with independent state verification and complete trace replay."
)
path.write_text(
    start
    + "<!-- HTTP_RESUME_RESULT_START -->\n\n"
    + bullet
    + "\n\n"
    + (
        "Both baseline and adapted arms had 100% schema-valid calls; this comparison controls the format-rejection confound.\n"
        if all_valid
        else "Consult the call-validity table before describing this as a semantic-only gain.\n"
    )
    + "<!-- HTTP_RESUME_RESULT_END -->"
    + end,
    encoding="utf-8",
    newline="\n",
)
print("Wrote measured results, README tables and a scoped resume bullet.")
