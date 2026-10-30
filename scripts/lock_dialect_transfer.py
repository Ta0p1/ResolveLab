"""Freeze every input of the dialect transfer test run. Refuses before registration or after
any test output exists."""

import json
import subprocess
from pathlib import Path

from resolvelab.casedesk.manifest import load_manifest
from resolvelab.dialects.assignment import load_assignment
from resolvelab.dialects.lock import build_lock
from resolvelab.evaluation import write_report
from resolvelab.store import utcnow

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local/v05"
LOCK = ROOT / "artifacts/v0.5/test-lock.json"
PROTOCOL = ROOT / "docs/dialect-transfer-protocol.md"


def git(*args):
    # check=True: a git that cannot read the repository must stop the lock, not pass silently.
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=ROOT, check=True
    ).stdout.strip()


def main():
    if LOCK.exists():
        raise SystemExit("Already locked")
    title = PROTOCOL.read_text(encoding="utf-8").splitlines()[0]
    if "not registered" in title or "draft" in title.lower():
        raise SystemExit("The protocol is still a draft; register it before locking")
    if git("status", "--porcelain", "src", "benchmarks", "scripts", "docs"):
        raise SystemExit("Commit source, benchmark, script and protocol changes before locking")
    study = json.loads((ROOT / "benchmarks/casedesk-v2-study.json").read_text(encoding="utf-8"))
    manifest = load_manifest(ROOT / study["manifest"])
    lock = build_lock(
        local=LOCAL,
        manifest=manifest,
        assignment=load_assignment(ROOT / "benchmarks/casedesk-dialects-v1.json", manifest),
        study=study,
        v04_lock=json.loads((ROOT / "artifacts/v0.4/test-lock.json").read_text(encoding="utf-8")),
        commit=git("rev-parse", "HEAD"),
        locked_at=utcnow(),
        seeds=study["training_seeds"],
    )
    write_report(LOCK, lock)
    print(LOCK, len(lock["adapters"]), "adapters locked")


if __name__ == "__main__":
    main()
