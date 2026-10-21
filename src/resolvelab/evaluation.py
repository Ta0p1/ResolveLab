import hashlib
import json
import platform
import statistics
import time
import uuid
from pathlib import Path

import httpx

from . import __version__
from .policies import OllamaPolicy
from .runner import Runner
from .scenarios import BY_ID
from .store import dumps, utcnow


def source_fingerprint() -> str:
    hasher = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        hasher.update(path.name.encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def model_metadata(model: str) -> dict:
    provider = OllamaPolicy(model)
    try:
        with httpx.Client(timeout=3, trust_env=False) as client:
            version = client.get(provider.base_url + "/api/version").json()
            models = client.get(provider.base_url + "/api/tags").json().get("models", [])
        info = next((m for m in models if m["name"] == model), {})
        return {
            "name": model,
            "digest": info.get("digest"),
            "details": info.get("details"),
            "ollama_version": version.get("version"),
            "temperature": 0.6,
            "thinking": True,
            "interaction": "native_tool_calls",
            "generation_seed": 42,
            "context_tokens": provider.context,
            "max_output_tokens": provider.max_output,
            "truncation_retries": 1,
            "retry_max_output_tokens": provider.retry_max_output,
        }
    except (httpx.HTTPError, ValueError):
        return {"name": model, "available": False}


def summarize(rows: list[dict]) -> list[dict]:
    result = []
    for policy in sorted({r["policy"] for r in rows}):
        items = [r for r in rows if r["policy"] == policy]
        n = len(items)
        resolved_eligible = [r for r in items if r["verdict"]["expected_outcome"] == "resolved"]
        durations = sorted(r["wall_seconds"] for r in items)
        result.append(
            {
                "policy": policy,
                "episodes": n,
                "passed": sum(r["verdict"]["passed"] for r in items),
                "pass_rate": sum(r["verdict"]["passed"] for r in items) / n,
                "resolved": sum(r["verdict"]["resolved"] for r in items),
                "resolvable_episodes": len(resolved_eligible),
                "escalations": sum(r["verdict"]["appropriate_escalation"] for r in items),
                "false_successes": sum(r["verdict"]["false_success"] for r in items),
                "duplicate_episodes": sum(r["verdict"]["duplicate_count"] > 0 for r in items),
                "errors": sum(r["status"] == "error" for r in items),
                "mean_tools": statistics.mean(r["tool_count"] for r in items),
                "median_seconds": statistics.median(durations),
                "input_tokens": sum(r["input_tokens"] for r in items),
                "output_tokens": sum(r["output_tokens"] for r in items),
            }
        )
    return result


def write_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
    try:
        for attempt in range(6):
            try:
                temp.replace(path)
                break
            except PermissionError:
                # Windows readers/antivirus may briefly deny rename of an open file.
                # Keep the prior complete report visible; never fall back to in-place writes.
                if attempt == 5:
                    raise
                time.sleep(0.01 * 2**attempt)
    finally:
        temp.unlink(missing_ok=True)


def new_report(policies, scenarios, seeds, model) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "status": "running",
        "created_at": utcnow(),
        "version": __version__,
        "suite": "sync-recovery-v1",
        "source_sha256": source_fingerprint(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "policies": policies,
        "scenarios": scenarios,
        "seeds": seeds,
        "model": model_metadata(model) if "ollama" in policies else None,
        "total": len(policies) * len(scenarios) * len(seeds),
        "completed": 0,
        "summary": [],
        "rows": [],
        "limitations": [
            "Synthetic, in-process sync service backed by real SQLite transactions; not production traffic.",
            "All scenario families are public development/regression cases, not a hidden generalization benchmark.",
            "Seeds vary record values and counts; they do not create independent fault families.",
            "Reference is hand-written for this runbook; naive is an intentionally weak append/retry baseline.",
            "Pass rate includes correct read-only escalations. Resolution and escalation are reported separately.",
            "Provider failures remain in the denominator. Wall time includes inference and local queuing.",
            "Local token counts are reported; no cloud price or training improvement is claimed.",
        ],
    }


def evaluate(runner: Runner, report: dict, path: Path, model: str = "qwen3:4b") -> dict:
    write_report(path, report)
    try:
        for seed in report["seeds"]:
            for scenario in report["scenarios"]:
                if scenario not in BY_ID:
                    raise ValueError(f"Unknown scenario: {scenario}")
                for policy in report["policies"]:
                    run_id = runner.store.create(
                        scenario, seed, policy, model if policy == "ollama" else None
                    )
                    run = runner.execute(run_id)
                    report["rows"].append(
                        {
                            k: run[k]
                            for k in (
                                "id",
                                "scenario",
                                "seed",
                                "policy",
                                "model",
                                "status",
                                "claim",
                                "verdict",
                                "tool_count",
                                "wall_seconds",
                                "input_tokens",
                                "output_tokens",
                                "error",
                            )
                        }
                    )
                    report["completed"] += 1
                    report["summary"] = summarize(report["rows"])
                    write_report(path, report)
        report["status"] = "completed"
    except Exception as exc:
        report["status"] = "error"
        report["error"] = f"{type(exc).__name__}: {exc}"
    report["finished_at"] = utcnow()
    write_report(path, report)
    return report


def export_trace(store, run_id: str) -> str:
    run = store.get(run_id)
    header = {k: run[k] for k in ("id", "scenario", "seed", "policy", "model", "status", "verdict")}
    lines = [
        dumps(
            {
                "type": "episode",
                **header,
                "training_eligible": False,
                "note": "Regression trace. Review and split provenance before using for training.",
            }
        )
    ]
    lines.extend(dumps({"type": "event", **e}) for e in run["events"])
    return "\n".join(lines) + "\n"
