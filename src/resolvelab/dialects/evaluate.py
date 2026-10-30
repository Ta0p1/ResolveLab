"""Resumable evaluation in dialects: the v0.4 report and summary, plus each episode's dialect.

Rows add the dialect name and its conventions (token style, pagination, time unit, the code
that means conflict), which are the protocol's pre-declared slices. The report's identity
adds the assignment digest, so a resumed run cannot mix assignments.
"""

import json
from pathlib import Path

from ..benchmark import digest
from ..casedesk.evaluate import episode_row, summarize
from ..evaluation import write_report
from ..store import dumps, utcnow
from ..training import file_hash
from .assignment import dialect_named
from .lock import current_source_hash
from .runner import run_dialect_episode


def dialect_columns(dialect):
    return {
        "dialect": dialect.name,
        "token_style": dialect.token,
        "cursor_style": dialect.cursor,
        "time_unit": dialect.unit,
        "conflict_code": dialect.codes[412],
    }


def evaluate(manifest, assignment, pool, arm, output, provider=None, resume=False, limit=None):
    """Evaluate ``arm`` on a pool, each episode in its assigned dialect (teacher if no provider)."""
    output = Path(output)
    traces = output.with_suffix("")
    adapter = arm.get("adapter")
    identity = {
        "manifest_sha256": digest(manifest),
        "assignment_sha256": digest(assignment),
        "source_sha256": current_source_hash(),
        "pool": pool,
        "arm": arm,
        "arm_sha256": digest(arm),
        "adapter_sha256": file_hash(Path(adapter) / "adapter_model.safetensors") if adapter else None,
    }
    if assignment["manifest_sha256"] != identity["manifest_sha256"]:
        raise ValueError("Assignment does not belong to this manifest")
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
        dialect = dialect_named(assignment["episodes"][spec["id"]])
        trace = run_dialect_episode(spec, dialect, provider, max_tools=arm.get("max_tools", 24))
        trace.pop("steps")
        trace["training_eligible"] = False
        path = traces / f"{spec['id']}.json"
        write_report(path, trace)
        item = episode_row(trace, path) | dialect_columns(dialect)
        report["rows"].append(item)
        report["summary"] = summarize(report["rows"])
        write_report(output, report)
        print(
            dumps(
                {k: item[k] for k in ("spec_id", "dialect", "passed", "failure_category", "tools")}
                | {"seconds": round(item["seconds"], 1)}
            ),
            flush=True,
        )
    report["summary"] = summarize(report["rows"])
    report["status"] = "completed"
    report["finished_at"] = utcnow()
    write_report(output, report)
    return report
