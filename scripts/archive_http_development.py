"""Preserve pre-test development explorations separately from registered test evidence."""

import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = root / "artifacts/v0.3/development"
destination.mkdir(parents=True, exist_ok=True)
names = [
    "http-base-dev",
    "http-large-dev",
    "http-base-oneshot-dev",
    "http-base-ordered-dev",
    "http-large-ordered-dev",
    "http-sft-3407-dev",
    "http-sft-42-dev",
    "http-sft-2026-dev",
    "http-ollama-cpu-dev",
    "http-ollama-reminder-dev",
]
lines = [
    "# Development history (excluded from test metrics)",
    "",
    "These runs informed integration/prompt choices before the test lock. Initial zero-shot and",
    "unordered one-shot variants are exploratory. Intermediate pre-lock source hashes were",
    "captured from the working tree; those snapshots are not standalone reproducible releases.",
    "The final primary source, data and prompt are committed and locked separately.",
    "",
    "`http-base-oneshot-dev` was interrupted after completed cases; its original report retains",
    "the last saved `running` status. Do not treat that partial run as a completed evaluation.",
    "The 4B development probes use CPU-only inference on two development cases; their latency",
    "is not compared with GPU test latency. All original JSON and completed traces are preserved.",
    "",
    "| Run | Saved status | Completed episodes | Passed |",
    "|---|---|---:|---:|",
]
for name in names:
    path = root / ".local" / f"{name}.json"
    if not path.exists():
        raise ValueError(f"Missing development evidence: {name}")
    report = json.loads(path.read_text(encoding="utf-8"))
    shutil.copyfile(path, destination / path.name)
    shutil.copytree(path.with_suffix(""), destination / name, dirs_exist_ok=True)
    summary = report["summary"]
    lines.append(
        f"| [{name}]({path.name}) | {report['status']} | {len(report['rows'])} | {summary['passed']} |"
    )
(destination / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print("Archived development runs without merging them into test metrics.")
