"""Render release evidence from completed reports; never manufacture benchmark rows."""

import json
from pathlib import Path

from resolvelab.evaluation import export_trace, source_fingerprint
from resolvelab.store import Store


def main():
    root = Path("artifacts")
    model = json.loads((root / "local-model-evaluation.json").read_text(encoding="utf-8"))
    offline = json.loads((root / "offline-evaluation.json").read_text(encoding="utf-8"))
    validation = json.loads((root / "validation.json").read_text(encoding="utf-8"))
    for report in (model, offline):
        if report["status"] != "completed" or report["completed"] != report["total"]:
            raise SystemExit("Reports must be complete before creating release evidence.")
        if report["source_sha256"] != source_fingerprint():
            raise SystemExit("Source changed after evaluation; do not label old results as current.")
    store = Store(".local/resolvelab.sqlite")
    trace_dir = root / "traces"
    trace_dir.mkdir(exist_ok=True)
    audits = []
    for row in model["rows"]:
        run = store.get(row["id"])
        if run["policy"] == "ollama":
            tools = [event for event in run["events"] if event["kind"] == "tool"]
            audits.append(
                {
                    "run_id": run["id"],
                    "scenario": run["scenario"],
                    "tools": [event["name"] for event in tools],
                    "read_untrusted_logs": any(event["name"] == "read_logs" for event in tools),
                    "passed": run["verdict"]["passed"],
                    "error": run["error"],
                }
            )
            (trace_dir / f"{run['scenario']}.jsonl").write_text(
                export_trace(store, run["id"]), encoding="utf-8"
            )
    (root / "trajectory-audit.json").write_text(json.dumps(audits, indent=2), encoding="utf-8")
    lines = [
        "# ResolveLab v0.1 — measured development results",
        "",
        f"Evaluation finished: `{model['finished_at']}`. All results below come from committed "
        "episode records and independent SQL outcome checks.",
        "",
        "**This is a ten-family synthetic, public development suite. It is not a held-out "
        "generalization or production reliability benchmark.**",
        "",
        "## Same-seed comparison",
        "",
        "All policies use seed 42 on all ten scenarios. A pass is verified recovery or a correct "
        "read-only escalation. Failures remain in the denominator.",
        "",
        "| Policy | Pass / total | Resolved / eligible | Correct escalations | False success claims | "
        "Mean tools | Median wall time |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in model["summary"]:
        name = {
            "naive": "Legacy retry (intentionally weak)",
            "reference": "Runbook (scripted)",
            "ollama": model["model"]["name"],
        }[s["policy"]]
        lines.append(
            f"| {name} | {s['passed']}/{s['episodes']} | {s['resolved']}/{s['resolvable_episodes']} | "
            f"{s['escalations']} | {s['false_successes']} | {s['mean_tools']:.1f} | {s['median_seconds']:.2f}s |"
        )
    lines += [
        "",
        "The reference policy is written for this runbook. The legacy policy is a failure "
        "demonstration, not a competitive baseline. Neither uses a model.",
        "",
        "## Local model episodes",
        "",
        "| Scenario | Outcome | Tool calls | Input / output tokens | Wall time |",
        "|---|---|---:|---:|---:|",
    ]
    for r in model["rows"]:
        if r["policy"] != "ollama":
            continue
        outcome = (
            "resolved"
            if r["verdict"]["resolved"]
            else ("correct escalation" if r["verdict"]["appropriate_escalation"] else "failed")
        )
        lines.append(
            f"| [{r['scenario']}](traces/{r['scenario']}.jsonl) | {outcome} | {r['tool_count']} | "
            f"{r['input_tokens']} / {r['output_tokens']} | {r['wall_seconds']:.2f}s |"
        )
    failures = [r for r in model["rows"] if r["policy"] == "ollama" and not r["verdict"]["passed"]]
    lines += ["", "## Failure analysis", ""]
    if failures:
        for r in failures:
            lines += [
                f"- **{r['scenario']}**: {r['error'] or 'The final state did not satisfy the checker.'} "
                f"Final missing records: {r['verdict']['missing_count']}; duplicates: "
                f"{r['verdict']['duplicate_count']}. No scripted recovery replaced the model's output."
            ]
    else:
        lines += [
            "No failed episodes in this one development-suite run. This does not establish generalization."
        ]
    injection = next(a for a in audits if a["scenario"] == "untrusted_log")
    lines += [
        "",
        (
            "The model read the untrusted log in the injection scenario. This is one exposed test case, "
            "not a general prompt-injection robustness result."
            if injection["read_untrusted_logs"]
            else "The model did **not** read the untrusted log in the injection scenario. Its passing result "
            "therefore does **not** demonstrate resistance to the injected instructions."
        ),
        "",
        "## Reproducibility",
        "",
        f"- Model: `{model['model']['name']}`, `{model['model']['details']['quantization_level']}`.",
        f"- Model digest: `{model['model']['digest']}`.",
        f"- Ollama: `{model['model']['ollama_version']}`; Python: `{model['python']}`; "
        f"platform: `{model['platform']}`.",
        f"- Recorded host GPU: {validation['hardware']['gpu']}, "
        f"{validation['hardware']['memory_mib']} MiB; driver {validation['hardware']['driver']}.",
        "- Native tool calling, thinking enabled, temperature 0.6, generation seed 42, "
        "8192 context tokens, 2048 generated tokens per decision, 18 tool calls per episode.",
        "- Wall time includes inference and loading. Token counts are provider-reported; no cloud price is claimed.",
        f"- Python source fingerprint: `{model['source_sha256']}`.",
        "- Dependency versions are pinned in [`constraints.txt`](../constraints.txt).",
        "",
        "## Additional validation",
        "",
    ]
    reference = next(s for s in offline["summary"] if s["policy"] == "reference")
    lines += [
        f"- Offline regression: {offline['completed']} episodes, two scripted policies, seeds 42/43/44. "
        f"Reference passed {reference['passed']}/{reference['episodes']} "
        f"({reference['resolved']} recoveries, {reference['escalations']} escalations).",
        f"- Python tests: {validation['python_tests']['passed']} passed on the validation host. "
        "A dependency deprecation warning "
        "was emitted for Starlette's legacy HTTPX test-client support.",
        "- Browser checks: recovery, false claims, escalation, trace/report downloads, evaluation "
        "navigation and mobile overflow verified in headless Microsoft Edge.",
        "- A clean virtual environment installed the wheel and exercised its CLI, HTTP API and bundled static assets.",
        (
            f"- Hosted CI passed for Python {', '.join(validation['ci']['python_versions'])} "
            f"on commit `{validation['ci']['commit'][:7]}`: [workflow run]({validation['ci']['url']})."
            if validation["hosted_ci"] == "success"
            else "- GitHub Actions configuration is included; hosted CI has not yet been verified."
        ),
        "",
        "## Evidence",
        "",
        "- [Complete same-seed report](local-model-evaluation.json)",
        "- [Offline regression report](offline-evaluation.json)",
        "- [Tool exposure audit](trajectory-audit.json)",
        "- [Local validation record](validation.json)",
        "- [Initial adapter failure](initial-adapter-failure.jsonl) and [development notes](../docs/experiments.md)",
        "- [Evaluation protocol](../docs/evaluation.md)",
        "",
        "No model training was performed. These results establish an inspectable baseline for "
        "future held-out evaluation and post-training experiments.",
        "",
    ]
    (root / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    # Make the measured reports available in this workspace's UI with their original IDs.
    reports_dir = Path(".local/reports")
    reports_dir.mkdir(exist_ok=True)
    for report in (offline, model):
        (reports_dir / f"{report['id']}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Release results, per-episode traces and exposure audit saved.")


if __name__ == "__main__":
    main()
