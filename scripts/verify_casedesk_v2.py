"""GPU-free audit of the v0.4 study: provenance, DAgger labels, and replay of every test trace.

Checks: the manifest regenerates; the locked source files, prompt and schema are unchanged;
expert data regenerates byte-for-byte; every DAgger label is re-derived from its learner state
and re-verified by teacher continuation; training reports match the locked data and adapters;
every test episode replays over real HTTP to the same observations, verdict and diagnostics;
and the registered analysis recomputes to the published numbers.
"""

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

from resolvelab.benchmark import digest
from resolvelab.casedesk.analysis import analyze
from resolvelab.casedesk.data import expert_rows
from resolvelab.casedesk.evaluate import summarize
from resolvelab.casedesk.manifest import build_manifest, load_manifest
from resolvelab.casedesk.runner import label_state, run_episode
from resolvelab.httpdesk.schema import action_schema, initial_messages
from resolvelab.store import dumps

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts/v0.4"
PACKAGE = ROOT / "src/resolvelab"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def locked_source_hash(files):
    h = hashlib.sha256()
    for name in sorted(files, key=lambda n: tuple(n.split("/"))):
        h.update(name.encode())
        h.update((PACKAGE / name).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def prefix_actions(messages):
    """Learner actions already taken, recovered from the conversation a DAgger row stores."""
    start = len(initial_messages("x"))
    return [json.loads(m["content"]) for m in messages[start:] if m["role"] == "assistant"]


def verify(every=1, replay_every=1):
    """Hashes of every trace and data file are always checked; sampling only thins replays."""
    lock = read(BUNDLE / "test-lock.json")
    study = read(ROOT / "benchmarks/casedesk-v2-study.json")
    manifest = load_manifest(ROOT / study["manifest"])
    assert build_manifest(manifest["master_seed"]) == manifest
    assert digest(manifest) == lock["manifest_sha256"] and digest(study) == lock["study_sha256"]
    assert locked_source_hash(lock["source_files"]) == lock["source_sha256"]
    assert digest(initial_messages("TASK_PLACEHOLDER")) == lock["prompt_sha256"]
    assert digest(action_schema()) == lock["schema_sha256"]

    data = zipfile.ZipFile(BUNDLE / "data.zip")
    for name, expected in lock["data_sha256"].items():
        assert sha(data.read(name.removeprefix("data/"))) == expected, name
    for pool in ("train_core", "train_pool", "dev"):
        rows, _ = expert_rows(manifest, pool)
        regenerated = "".join(dumps(r) + "\n" for r in rows).encode()
        assert sha(regenerated) == lock["data_sha256"][f"data/expert-{pool}.jsonl"], pool
    specs = {s["id"]: s for rows in manifest["episodes"].values() for s in rows}
    labels = 0
    for name in data.namelist():
        if not (name.startswith("dagger-") and name.endswith(".jsonl") and "/" not in name):
            continue
        for index, line in enumerate(io.TextIOWrapper(data.open(name), encoding="utf-8")):
            if index % every:
                continue
            row = json.loads(line)
            label, verified, _ = label_state(specs[row["spec_id"]], prefix_actions(row["messages"]))
            assert verified and label == row["target"], (name, row["spec_id"], row["step"])
            labels += 1

    for key, entry in lock["adapters"].items():
        if key.startswith("v03-"):
            continue
        training = read(BUNDLE / "training" / f"{key}.json")
        assert training["status"] == "completed"
        best = min(training["epochs"], key=lambda e: e["dev_loss"])
        assert best["checkpoint"] == training["selected_checkpoint"] == entry["checkpoint"]
        assert best["adapter_sha256"] == entry["sha256"]
        assert sha((BUNDLE / "training" / f"{key}.json").read_bytes()) == entry["training_report_sha256"]

    replayed = 0
    for report_path in sorted((BUNDLE / "test").glob("*.json")):
        report = read(report_path)
        arm = report["arm"]
        key = arm["name"] if arm.get("seed") is None else f"{arm['name']}-{arm['seed']}"
        assert report["status"] == "completed" and report["created_at"] > lock["locked_at"]
        assert report["manifest_sha256"] == lock["manifest_sha256"]
        assert report["source_sha256"] == lock["source_sha256"]
        if key in lock["adapters"]:
            assert report["adapter_sha256"] == lock["adapters"][key]["sha256"], key
        traces = zipfile.ZipFile(BUNDLE / "traces" / "test" / f"{report_path.stem}.zip")
        for index, row in enumerate(report["rows"]):
            raw = traces.read(row["trace"])
            assert sha(raw) == row["trace_sha256"]
            if index % replay_every:
                continue
            trace = json.loads(raw)
            spec = specs[row["spec_id"]]
            actions = [d["action"] for d in trace["decisions"] if "action" in d]
            again = run_episode(spec, forced=actions, max_tools=len(actions))
            assert again["observations"] == trace["observations"], row["spec_id"]
            assert again["verdict"] == trace["verdict"], row["spec_id"]
            assert again["diagnostics"] == trace["diagnostics"], row["spec_id"]
            replayed += 1
        assert summarize(report["rows"]) == report["summary"]

    published = read(BUNDLE / "analysis-test.json")
    assert json.loads(json.dumps(analyze(BUNDLE / "test", manifest, "test"))) == published
    return labels, replayed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dagger-every", type=int, default=1, help="re-verify every Nth DAgger label")
    parser.add_argument("--replay-every", type=int, default=1, help="replay every Nth test episode")
    args = parser.parse_args()
    labels, replayed = verify(args.dagger_every, args.replay_every)
    print(f"Verified provenance, {labels} DAgger labels and {replayed} real-HTTP test episode replays.")
