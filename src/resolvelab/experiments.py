"""Paired, resumable composition evaluation with every failure in the denominator."""

import json
import random
import statistics
import uuid
from pathlib import Path

from .benchmark import cases, digest
from .evaluation import export_trace, source_fingerprint, summarize, write_report
from .runner import MAX_STEPS, Runner
from .store import Store, utcnow
from .training import file_hash


def evaluate_compositions(
    manifest, config, split, output, data_dir, adapter=None, reference=False, resume=False
):
    output, data_dir = Path(output), Path(data_dir)
    policy = "reference" if reference else "hf-sft" if adapter else "hf-base"
    adapter_hash = file_hash(Path(adapter) / "adapter_model.safetensors") if adapter else None
    if output.exists():
        if not resume:
            raise ValueError("Report exists; use --resume for an incomplete evaluation")
        report = json.loads(output.read_text(encoding="utf-8"))
        expected = (digest(manifest), digest(config), split, policy, adapter_hash, source_fingerprint())
        actual = tuple(
            report[k]
            for k in (
                "manifest_sha256",
                "config_sha256",
                "split",
                "policy",
                "adapter_sha256",
                "source_sha256",
            )
        )
        if actual != expected or report["status"] == "completed":
            raise ValueError("Cannot resume completed or incompatible experiment")
    else:
        report = {
            "id": uuid.uuid4().hex,
            "status": "running",
            "created_at": utcnow(),
            "suite": manifest["name"],
            "split": split,
            "policy": policy,
            "manifest_sha256": digest(manifest),
            "config_sha256": digest(config),
            "source_sha256": source_fingerprint(),
            "adapter_sha256": adapter_hash,
            "max_tools": MAX_STEPS,
            "total": len(list(cases(manifest, split))),
            "completed": 0,
            "rows": [],
            "summary": [],
        }
    store = Store(data_dir / "evaluation.sqlite")
    provider = None
    if not reference:
        from .hf_policy import HFPolicy

        provider = HFPolicy(
            config["base"], config["revision"], adapter, config["max_output"], config["context"]
        )
        report["model"] = provider.metadata
    runner = Runner(store, provider)
    report["status"] = "running"
    report.pop("error", None)
    write_report(output, report)
    done = {(r["scenario"], r["seed"]) for r in report["rows"]}
    try:
        for spec, seed in cases(manifest, split):
            if (spec.id, seed) in done:
                continue
            run_id = store.create(spec.id, seed, policy, config["base"], spec=spec)
            run = runner.execute(run_id)
            row = {
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
            row["invalid_arguments"] = sum(
                e["kind"] == "tool" and e["result"].get("error") == "invalid_arguments"
                for e in run["events"]
            )
            row["protocol_errors"] = sum(e["name"] == "invalid_response" for e in run["events"])
            row["injection_exposed"] = any(
                e["name"] == "read_logs" and "injection" in spec.faults for e in run["events"]
            )
            row["failure_category"] = (
                "passed"
                if run["verdict"]["passed"]
                else "protocol"
                if row["protocol_errors"]
                else "false_success"
                if run["verdict"]["false_success"]
                else "budget_or_incomplete"
            )
            trace_dir = output.parent / (output.stem + "-traces")
            trace_dir.mkdir(parents=True, exist_ok=True)
            trace = trace_dir / f"{spec.id}-{seed}.jsonl"
            trace.write_text(export_trace(store, run_id), encoding="utf-8")
            row["trace"] = f"{trace_dir.name}/{trace.name}"
            row["trace_sha256"] = file_hash(trace)
            report["rows"].append(row)
            report["completed"] = len(report["rows"])
            report["summary"] = summarize(report["rows"])
            write_report(output, report)
            print(
                f"{policy} {split} {report['completed']}/{report['total']} "
                f"{spec.id}/{seed}: {row['failure_category']}",
                flush=True,
            )
        report["status"] = "completed"
    except Exception as exc:
        report["status"] = "error"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at"] = utcnow()
        write_report(output, report)
    return report


def compare(base, trained):
    for key in ("manifest_sha256", "config_sha256", "split", "source_sha256", "max_tools"):
        if base[key] != trained[key]:
            raise ValueError(f"Unpaired experiments: {key}")
    for report in (base, trained):
        if report["status"] != "completed" or len(report["rows"]) != report["total"]:
            raise ValueError("Incomplete evaluation")

    def indexed(report):
        rows = {(r["scenario"], r["seed"]): r for r in report["rows"]}
        if len(rows) != len(report["rows"]):
            raise ValueError("Duplicate evaluation cases")
        return rows

    before, after = indexed(base), indexed(trained)
    if before.keys() != after.keys():
        raise ValueError("Mismatched case sets")
    clusters = {}
    wins = losses = ties = 0
    for key, row in before.items():
        delta = int(after[key]["verdict"]["passed"]) - int(row["verdict"]["passed"])
        clusters.setdefault(key[0], []).append(delta)
        wins += delta > 0
        losses += delta < 0
        ties += delta == 0
    # Seeds within a fault template are correlated. Resample templates, not rows.
    means = [statistics.mean(v) for v in clusters.values()]
    rng = random.Random(2026)
    draws = sorted(statistics.mean(rng.choices(means, k=len(means))) for _ in range(10000))
    return {
        "split": base["split"],
        "manifest_sha256": base["manifest_sha256"],
        "base": base["summary"],
        "sft": trained["summary"],
        "paired_episodes": len(before),
        "templates": len(clusters),
        "wins": wins,
        "regressions": losses,
        "ties": ties,
        "pass_rate_delta": (wins - losses) / len(before),
        "template_bootstrap_95_interval": [draws[249], draws[9749]],
        "limitations": [
            "Synthetic composition holdout in one service, not external production incidents.",
            "One model and one training seed. Sampling uncertainty does not include training variance.",
            "Few fault templates; the cluster interval is exploratory, not a broad capability claim.",
            "Greedy decoding and JSON protocol are identical for base and SFT; no policy fallback.",
        ],
    }
