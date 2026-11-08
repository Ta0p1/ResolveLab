"""Run a v2 evaluation's episodes concurrently, keeping ``casedesk.evaluate``'s report.

Every episode owns its world and its real-socket ``DeskServer`` on port 0, so concurrent
episodes share nothing but the model behind the provider. ``workers`` episodes run at once in
a thread pool, and each running episode holds a provider instance of its own: ``anthropic:``
keeps the current episode's conversation in its instance, and the others are stateless
clients of a server. The report, the identity check, one trace file per episode and the
atomic writer are those of ``casedesk.evaluate``. Its rows stay in manifest order whatever
order episodes finish in, and the report is rewritten after every episode, so ``resume``
continues an interrupted run with any number of workers.

``workers=1`` runs the episodes one after another in the calling thread, as
``casedesk.evaluate`` does.
"""

import json
import queue
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing
from pathlib import Path

from ..benchmark import digest
from ..evaluation import write_report
from ..httpdesk.benchmark import source_hash
from ..store import dumps, utcnow
from ..training import file_hash
from .evaluate import episode_row, summarize
from .runner import MAX_TOOLS, run_episode

# Providers that cannot serve concurrent episodes, and what to do instead.
SERIAL = {
    "hf": (
        "hf: decodes with one local GPU model in this process, one sequence at a time. "
        "Use --workers 1, or serve the model with vLLM and evaluate it as openai:<served-name>."
    ),
}


def check_workers(provider, workers):
    """Refuse a worker count the provider cannot serve, before any model is loaded."""
    if workers < 1:
        raise ValueError(f"--workers must be at least 1, got {workers}")
    if workers > 1 and provider in SERIAL:
        raise ValueError(f"--workers {workers} is not supported for {SERIAL[provider]}")


def identity(manifest, pool, arm):
    """The report fields a resumed run must match, as ``casedesk.evaluate`` records them.

    An arm from ``providers.make_provider`` records a local adapter by a portable name and
    carries its ``adapter_sha256``; any other arm names a loadable adapter directory, hashed
    the way ``casedesk.evaluate`` hashes it.
    """
    adapter = arm.get("adapter")
    if "adapter_sha256" in arm:
        adapter_sha256 = arm["adapter_sha256"]
    else:
        adapter_sha256 = file_hash(Path(adapter) / "adapter_model.safetensors") if adapter else None
    return {
        "manifest_sha256": digest(manifest),
        "source_sha256": source_hash(),
        "pool": pool,
        "arm": arm,
        "arm_sha256": digest(arm),
        "adapter_sha256": adapter_sha256,
    }


def finished(pending, run, workers, position):
    """Yield ``(spec, trace)`` as episodes finish: inline for one worker, else from a pool.

    Closing the generator cancels the episodes that have not started and waits for the
    running ones, whose traces are then dropped (a resumed run repeats them).
    """
    if workers == 1:
        for spec in pending:
            yield spec, run(spec)
        return
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="casedesk-episode")
    try:
        futures = {executor.submit(run, spec): spec for spec in pending}
        running = set(futures)
        while running:
            # A bounded wait keeps Ctrl-C responsive on Windows.
            done, running = wait(running, timeout=0.5, return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda f: position[futures[f]["id"]]):
                yield futures[future], future.result()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def evaluate(
    manifest, pool, arm, output, provider=None, resume=False, limit=None, *, workers=1, spawn=None
):
    """``casedesk.evaluate.evaluate`` with ``workers`` episodes at a time.

    ``provider`` None means the scripted teacher. With more than one worker, ``spawn()`` must
    return another provider configured like ``provider``; each running episode uses its own.
    """
    check_workers(arm.get("provider"), workers)
    output = Path(output)
    traces = output.with_suffix("")
    expected = identity(manifest, pool, arm)
    position = {spec["id"]: k for k, spec in enumerate(manifest["episodes"][pool])}
    specs = manifest["episodes"][pool][:limit]
    if output.exists():
        report = json.loads(output.read_text(encoding="utf-8"))
        if (
            not resume
            or report["status"] == "completed"
            or any(report[k] != v for k, v in expected.items())
        ):
            raise ValueError("Existing or incompatible report")
    else:
        report = {
            **expected,
            "created_at": utcnow(),
            "status": "running",
            "total": len(specs),
            "rows": [],
        }
    done = {r["spec_id"] for r in report["rows"]}
    pending = [spec for spec in specs if spec["id"] not in done]
    workers = max(1, min(workers, len(pending)))
    models = [provider]
    if provider is not None and workers > 1:
        if spawn is None:
            raise ValueError("More than one worker needs spawn() to create a provider per episode")
        models += [spawn() for _ in range(workers - 1)]
        if any(model.metadata != provider.metadata for model in models):
            raise ValueError("Provider instances disagree on their metadata")
    else:
        models *= workers
    if provider is not None:
        report["model"] = provider.metadata
    traces.mkdir(parents=True, exist_ok=True)
    write_report(output, report)

    idle = queue.SimpleQueue()
    for model in models:
        idle.put(model)

    def run(spec):
        model = idle.get()
        try:
            trace = run_episode(spec, model, max_tools=arm.get("max_tools", MAX_TOOLS))
        finally:
            idle.put(model)
        trace.pop("steps")
        trace["training_eligible"] = False
        return trace

    with closing(finished(pending, run, workers, position)) as results:
        for spec, trace in results:
            path = traces / f"{spec['id']}.json"
            write_report(path, trace)
            item = episode_row(trace, path)
            report["rows"].append(item)
            report["rows"].sort(key=lambda row: position[row["spec_id"]])
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
