"""Real-HTTP rollouts, verified data collection, and paired outcome evaluation."""

import copy
import json
import random
import statistics
import time
from pathlib import Path

from ..benchmark import digest
from ..evaluation import write_report
from ..policies import PolicyResponseError
from ..store import dumps, utcnow
from ..training import file_hash
from .adapter import DeskAdapter
from .benchmark import cases, source_hash, validate_rows
from .grading import grade
from .reference import reference_next
from .schema import action_json, append_observation, initial_messages, validate_action
from .service import DeskServer, DeskState


def episode(template, seed, provider=None, max_tools=24, replay=None):
    state = DeskState(template["faults"], seed)
    messages = initial_messages(state.task)
    observations, decisions, training = [], [], []
    claim, error = None, None
    started = time.perf_counter()
    with DeskServer(state) as server:
        adapter = DeskAdapter(server.url)
        try:
            for step in range(max_tools):
                if replay is not None:
                    if step >= len(replay):
                        break
                    action = validate_action(replay[step])
                    usage, seconds = {}, 0
                elif provider is None:
                    action = reference_next(state.task, observations)
                    usage, seconds = {}, 0
                else:
                    try:
                        action, usage, seconds = provider.next(messages)
                    except PolicyResponseError as exc:
                        decisions.append(
                            {
                                "step": step,
                                "error": str(exc),
                                "usage": exc.usage,
                                "seconds": exc.seconds,
                            }
                        )
                        error = exc.usage.get("failure_category", "protocol_error")
                        break
                    except Exception as exc:
                        decisions.append(
                            {
                                "step": step,
                                "error": f"{type(exc).__name__}: {exc}",
                                "usage": {},
                                "seconds": 0,
                            }
                        )
                        error = "inference_error"
                        break
                decisions.append(
                    {"step": step, "action": action.model_dump(), "usage": usage, "seconds": seconds}
                )
                training.append(
                    {
                        "messages": copy.deepcopy(messages),
                        "target": action.model_dump(),
                        "target_text": action_json(action.model_dump()),
                        "step": step,
                    }
                )
                result = adapter.dispatch(action)
                observation = {"name": action.name, "arguments": action.arguments, "result": result}
                observations.append(observation)
                append_observation(messages, action.name, action.arguments, result)
                if action.name == "finish":
                    claim = action.arguments["outcome"]
                    break
        finally:
            adapter.close()
    verdict = grade(state, claim)
    if not claim and not error:
        error = "tool_budget"
    return {
        "template": template["id"],
        "seed": seed,
        "task": state.task,
        "faults": template["faults"],
        "verdict": verdict,
        "error": error,
        "decisions": decisions,
        "observations": observations,
        "http_client": adapter.requests,
        "http_server": state.http_events,
        "initial_state": state.initial,
        "final_state": state.tickets,
        "commits": state.commits,
        "wall_seconds": time.perf_counter() - started,
        "training": training,
    }


def collect(manifest, output):
    output = Path(output)
    if output.exists():
        raise ValueError("Training data already exists")
    output.mkdir(parents=True)
    report = {
        "manifest_sha256": digest(manifest),
        "source_sha256": source_hash(),
        "teacher": "scripted_http_runbook_v1",
        "splits": {},
    }
    for split in ("train", "dev"):
        rows, episodes = [], []
        for template, seed in cases(manifest, split):
            trace = episode(template, seed)
            if not trace["verdict"]["passed"]:
                raise ValueError(f"Teacher failed: {template['id']} / {seed}: {trace['verdict']}")
            for item in trace.pop("training"):
                rows.append(
                    {
                        **item,
                        "split": split,
                        "template": template["id"],
                        "seed": seed,
                        "verified_teacher": True,
                        "manifest_sha256": digest(manifest),
                    }
                )
            episodes.append(
                {"template": template["id"], "seed": seed, "steps": len(trace["observations"])}
            )
        validate_rows(rows, manifest, split)
        path = output / f"{split}.jsonl"
        path.write_text("".join(dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n")
        report["splits"][split] = {
            "episodes": episodes,
            "examples": len(rows),
            "sha256": file_hash(path),
        }
    write_report(output / "provenance.json", report)
    return report


def summarize(rows):
    n = len(rows)
    attempts = sum(r["decisions"] for r in rows)
    return {
        "episodes": n,
        "passed": sum(r["passed"] for r in rows),
        "success_rate": sum(r["passed"] for r in rows) / n if n else 0,
        "decision_attempts": attempts,
        "json_valid_rate": sum(r["json_valid"] for r in rows) / attempts if attempts else None,
        "schema_valid_rate": sum(r["schema_valid"] for r in rows) / attempts if attempts else None,
        "unsafe_mutations": sum(r["unsafe_mutations"] for r in rows),
        "redundant_commits": sum(r["redundant_commits"] for r in rows),
        "false_successes": sum(r["false_success"] for r in rows),
        "mean_tools": statistics.mean(r["tools"] for r in rows) if n else 0,
        "median_seconds": statistics.median(r["seconds"] for r in rows) if n else 0,
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "resolved_passed": sum(r["passed"] and r["claim"] == "resolved" for r in rows),
        "escalated_passed": sum(r["passed"] and r["claim"] == "escalated" for r in rows),
        "semantic_failures_with_valid_calls": sum(
            not r["passed"] and r["schema_valid"] == r["decisions"] for r in rows
        ),
        "passed_after_http_error": {
            str(status): sum(r["passed"] and status in r["http_statuses"] for r in rows)
            for status in (403, 412, 429, 502)
        },
    }


def evaluate(manifest, config, split, output, adapter=None, reference=False, resume=False):
    output = Path(output)
    traces = output.with_suffix("")
    policy = "reference" if reference else "sft" if adapter else "base"
    identity = {
        "manifest_sha256": digest(manifest),
        "config_sha256": digest(config),
        "source_sha256": source_hash(),
        "split": split,
        "policy": policy,
        "adapter_sha256": file_hash(Path(adapter) / "adapter_model.safetensors") if adapter else None,
    }
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
            "config": config,
            "total": len(list(cases(manifest, split))),
            "rows": [],
        }
    provider = None
    if not reference:
        from .policy import StructuredPolicy

        provider = StructuredPolicy(config, adapter)
        report["model"] = provider.metadata
    traces.mkdir(parents=True, exist_ok=True)
    done = {(r["template"], r["seed"]) for r in report["rows"]}
    write_report(output, report)
    for template, seed in cases(manifest, split):
        if (template["id"], seed) in done:
            continue
        trace = episode(template, seed, provider, config["max_tools"])
        trace.pop("training")
        trace["training_eligible"] = False
        path = traces / f"{template['id']}-{seed}.json"
        write_report(path, trace)
        calls = trace["decisions"]
        row = {
            "template": template["id"],
            "seed": seed,
            **trace["verdict"],
            "error": trace["error"],
            "tools": len(trace["observations"]),
            "decisions": len(calls),
            "json_valid": sum(c["usage"].get("json_valid", reference) for c in calls),
            "schema_valid": sum(c["usage"].get("schema_valid", reference) for c in calls),
            "output_tokens": sum(c["usage"].get("output_tokens", 0) for c in calls),
            "input_tokens": sum(c["usage"].get("input_tokens", 0) for c in calls),
            "seconds": trace["wall_seconds"],
            "trace": path.name,
            "trace_sha256": file_hash(path),
            "http_statuses": [
                o["result"]["status"] for o in trace["observations"] if "status" in o["result"]
            ],
        }
        report["rows"].append(row)
        report["summary"] = summarize(report["rows"])
        write_report(output, report)
        print(
            dumps(
                {
                    "template": row["template"],
                    "seed": seed,
                    "passed": row["passed"],
                    "error": row["error"],
                    "tools": row["tools"],
                    "seconds": round(row["seconds"], 2),
                }
            ),
            flush=True,
        )
    report["status"] = "completed"
    report["finished_at"] = utcnow()
    write_report(output, report)
    return report


def compare(base, trained):
    if base["status"] != "completed" or trained["status"] != "completed":
        raise ValueError("Incomplete reports")
    if base["policy"] != "base" or trained["policy"] != "sft":
        raise ValueError("Requires base versus trained model reports")
    if any(len(r["rows"]) != r["total"] for r in (base, trained)):
        raise ValueError("Missing episodes")
    for key in ("source_sha256", "manifest_sha256", "split"):
        if base[key] != trained[key]:
            raise ValueError(f"Mismatched {key}")
    for key in ("base", "revision", "max_output", "context", "max_tools", "decoder"):
        if base["config"][key] != trained["config"][key]:
            raise ValueError(f"Unmatched model or budget: {key}")
    for key in (
        "schema_sha256",
        "prompt_sha256",
        "protocol",
        "decoder_version",
        "thinking",
        "do_sample",
        "dtype",
        "retries",
        "force_json_field_order",
    ):
        if base["model"][key] != trained["model"][key]:
            raise ValueError(f"Mismatched model protocol: {key}")
    left = {(r["template"], r["seed"]): r for r in base["rows"]}
    right = {(r["template"], r["seed"]): r for r in trained["rows"]}
    if (
        not left
        or set(left) != set(right)
        or len(left) != len(base["rows"])
        or len(right) != len(trained["rows"])
    ):
        raise ValueError("Mismatched or duplicate cases")
    deltas = {k: int(right[k]["passed"]) - int(v["passed"]) for k, v in left.items()}
    groups = {}
    for (template, _), delta in deltas.items():
        groups.setdefault(template, []).append(delta)
    values = [statistics.mean(v) for v in groups.values()]
    rng = random.Random(2026)
    draws = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(10000))
    return {
        "paired_episodes": len(left),
        "templates": len(groups),
        "wins": sum(v == 1 for v in deltas.values()),
        "regressions": sum(v == -1 for v in deltas.values()),
        "ties": sum(v == 0 for v in deltas.values()),
        "success_delta": statistics.mean(deltas.values()),
        "template_bootstrap_95ci": [draws[250], draws[9749]],
        "base": base["summary"],
        "trained": trained["summary"],
        "limitation": "Public synthetic composition holdout; clusters are templates, not independent record seeds.",
    }
