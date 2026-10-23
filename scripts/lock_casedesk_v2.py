"""Freeze every input of the v2 test run. Refuses once any test output exists."""

import json
import subprocess
from pathlib import Path

from resolvelab.benchmark import digest
from resolvelab.casedesk.manifest import load_manifest
from resolvelab.evaluation import write_report
from resolvelab.httpdesk.benchmark import source_hash
from resolvelab.httpdesk.schema import action_schema, initial_messages
from resolvelab.store import utcnow
from resolvelab.training import file_hash

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local/v04"
LOCK = ROOT / "artifacts/v0.4/test-lock.json"


def git(*args):
    # check=True: a git that cannot read the repository must stop the lock, not pass silently.
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=ROOT, check=True
    ).stdout.strip()


def main():
    if LOCK.exists():
        raise SystemExit("Already locked")
    if any((LOCAL / "eval/test").glob("*.json")):
        raise SystemExit("Test outputs exist; a lock must precede them")
    study = json.loads((ROOT / "benchmarks/casedesk-v2-study.json").read_text(encoding="utf-8"))
    manifest = load_manifest(ROOT / study["manifest"])
    v03 = json.loads((ROOT / "artifacts/v0.3/test-lock.json").read_text(encoding="utf-8"))
    if git("status", "--porcelain", "src", "benchmarks", "scripts"):
        raise SystemExit("Commit source, benchmark and script changes before locking")
    adapters, training = {}, {}
    for seed in study["training_seeds"]:
        adapters[f"v03-lora-{seed}"] = {"sha256": v03["selected_adapters"][str(seed)]["sha256"]}
        for arm in ("bc", "bc-volume", "dagger"):
            run = LOCAL / "runs" / f"{arm}-{seed}"
            report = json.loads((run / "training.json").read_text(encoding="utf-8"))
            if report["status"] != "completed":
                raise SystemExit(f"{run} incomplete")
            checkpoint = report["selected_checkpoint"]
            adapters[f"{arm}-{seed}"] = {
                "checkpoint": checkpoint,
                "sha256": file_hash(run / checkpoint / "adapter_model.safetensors"),
                "training_report_sha256": file_hash(run / "training.json"),
            }
            training[f"{arm}-{seed}"] = {k: report[k] for k in ("data_sha256", "examples", "epochs")}
    data = {
        p.relative_to(LOCAL).as_posix(): file_hash(p) for p in sorted((LOCAL / "data").rglob("*.jsonl"))
    }
    dev = {p.name: file_hash(p) for p in sorted((LOCAL / "eval/dev").glob("*.json"))}
    lock = {
        "phase": "test",
        "locked_at": utcnow(),
        "commit": git("rev-parse", "HEAD"),
        "manifest_sha256": digest(manifest),
        "study_sha256": digest(study),
        "source_sha256": source_hash(),
        # The files that hash covers, so later versions can re-check exactly this set.
        "source_files": sorted(
            p.relative_to(ROOT / "src/resolvelab").as_posix()
            for p in [
                *(ROOT / "src/resolvelab").rglob("*.py"),
                ROOT / "src/resolvelab/httpdesk/demo.json",
            ]
        ),
        "prompt_sha256": digest(initial_messages("TASK_PLACEHOLDER")),
        "schema_sha256": digest(action_schema()),
        "data_sha256": data,
        "dev_report_sha256": dev,
        "adapters": adapters,
        "training": training,
    }
    write_report(LOCK, lock)
    print(LOCK, len(adapters), "adapters locked")


if __name__ == "__main__":
    main()
