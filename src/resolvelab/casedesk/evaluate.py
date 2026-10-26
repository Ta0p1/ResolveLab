"""Resumable v2 evaluation: one trace file per episode, identity-checked report."""

import json
import statistics
from pathlib import Path

from ..benchmark import digest
from ..evaluation import write_report
from ..httpdesk.benchmark import source_hash
from ..store import dumps, utcnow
from ..training import file_hash
from .runner import run_episode
from .stats import wilson


def episode_row(trace, path):
    calls = trace["decisions"]
    usage = [c.get("usage", {}) for c in calls]
    verdict, spec = trace["verdict"], trace["spec"]
    return {
        "spec_id": spec["id"],
        "composition": spec["composition"],
        **{
            k: verdict[k]
            for k in (
                "passed",
                "claim",
                "failure_category",
                "unsafe_mutations",
                "redundant_commits",
                "false_success",
                "spurious_escalation",
                "justified_escalation",
                "v03_passed",
            )
        },
        **trace["diagnostics"],
        "factors": trace["factors"],
        "error": trace["error"],
        "tools": len(trace["observations"]),
        "decisions": len(calls),
        "schema_valid": sum(u.get("schema_valid", False) for u in usage),
        "output_tokens": sum(u.get("output_tokens", 0) for u in usage),
        "thinking_tokens": sum(u.get("thinking_tokens", 0) for u in usage),
        "input_tokens": sum(u.get("input_tokens", 0) for u in usage),
        "seconds": trace["wall_seconds"],
        "trace": path.name,
        "trace_sha256": file_hash(path),
    }


def summarize(rows):
    n = len(rows)
    passed = sum(r["passed"] for r in rows)
    located = [r for r in rows if r["located_target"]]
    decisions = sum(r["decisions"] for r in rows)
    return {
        "episodes": n,
        "passed": passed,
        "success_rate": passed / n if n else 0,
        "wilson_95": wilson(passed, n),
        "resolved_passed": sum(r["passed"] and r["claim"] == "resolved" for r in rows),
        "escalated_passed": sum(r["passed"] and r["claim"] == "escalated" for r in rows),
        "unsafe_mutations": sum(r["unsafe_mutations"] for r in rows),
        "redundant_commits": sum(r["redundant_commits"] for r in rows),
        "false_successes": sum(r["false_success"] for r in rows),
        "spurious_escalations": sum(r["spurious_escalation"] for r in rows),
        "v03_grader_passed": sum(r["v03_passed"] for r in rows),
        "schema_valid_rate": sum(r["schema_valid"] for r in rows) / decisions if decisions else None,
        "located_target": len(located),
        "passed_given_located": sum(r["passed"] for r in located),
        "failure_categories": dict(
            sorted(
                {
                    c: sum(r["failure_category"] == c for r in rows)
                    for c in {r["failure_category"] for r in rows} - {None}
                }.items()
            )
        ),
        "mean_tools": statistics.mean(r["tools"] for r in rows) if n else 0,
        "median_seconds": statistics.median(r["seconds"] for r in rows) if n else 0,
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "thinking_tokens": sum(r["thinking_tokens"] for r in rows),
        "input_tokens": sum(r["input_tokens"] for r in rows),
    }


def evaluate(manifest, pool, arm, output, provider=None, resume=False, limit=None):
    """Evaluate ``arm`` on a pool. ``provider`` None means the scripted teacher (env check)."""
    output = Path(output)
    traces = output.with_suffix("")
    adapter = arm.get("adapter")
    identity = {
        "manifest_sha256": digest(manifest),
        "source_sha256": source_hash(),
        "pool": pool,
        "arm": arm,
        "arm_sha256": digest(arm),
        "adapter_sha256": file_hash(Path(adapter) / "adapter_model.safetensors") if adapter else None,
    }
    specs = manifest["episodes"][pool][:limit]
    if output.exists():
        report = json.loads(output.read_text(encoding="utf-8"))
        if (
            not resume
            or report["status"] == "completed"
            or any(report[k] != v for k, v in identity.items())
        ):
            raise ValueError("Existing or incompatible report")
    else:
        report = {
            **identity,
            "created_at": utcnow(),
            "status": "running",
            "total": len(specs),
            "rows": [],
        }
    if provider is not None:
        report["model"] = provider.metadata
    traces.mkdir(parents=True, exist_ok=True)
    done = {r["spec_id"] for r in report["rows"]}
    write_report(output, report)
    for spec in specs:
        if spec["id"] in done:
            continue
        trace = run_episode(spec, provider, max_tools=arm.get("max_tools", 24))
        trace.pop("steps")
        trace["training_eligible"] = False
        path = traces / f"{spec['id']}.json"
        write_report(path, trace)
        item = episode_row(trace, path)
        report["rows"].append(item)
        report["summary"] = summarize(report["rows"])
        write_report(output, report)
        print(
            dumps(
                {k: item[k] for k in ("spec_id", "passed", "failure_category", "tools")}
                | {"seconds": round(item["seconds"], 1)}
            ),
            flush=True,
        )
    report["summary"] = summarize(report["rows"])
    report["status"] = "completed"
    report["finished_at"] = utcnow()
    write_report(output, report)
    return report
