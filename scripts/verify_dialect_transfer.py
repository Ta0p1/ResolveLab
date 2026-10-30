"""GPU-free audit of the dialect transfer bundle (``artifacts/v0.5``), once it exists.

Checks the lock's inputs, regenerates expert data, re-derives every DAgger label from its
learner state, checks training reports against the locked adapters, replays every test
episode in its dialect (the study-contract runs in the canonical one) over real HTTP, and
recomputes the registered analysis. Exits cleanly, saying so, while there is no bundle.
"""

import argparse
import io
import json
import zipfile
from pathlib import Path

from resolvelab.casedesk.manifest import load_manifest
from resolvelab.dialects.analysis import analyze
from resolvelab.dialects.assignment import load_assignment
from resolvelab.dialects.audit import (
    same,
    sha,
    verify_dagger_rows,
    verify_expert_rows,
    verify_inputs,
    verify_reports,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts/v0.5"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify(every=1, replay_every=1):
    lock = read(BUNDLE / "test-lock.json")
    study = read(ROOT / "benchmarks/casedesk-v2-study.json")
    manifest = load_manifest(ROOT / study["manifest"])
    assignment = load_assignment(ROOT / "benchmarks/casedesk-dialects-v1.json", manifest)
    verify_inputs(lock, manifest, assignment, study)

    data = zipfile.ZipFile(BUNDLE / "data.zip")
    for name, expected in lock["data_sha256"].items():
        assert sha(data.read(name.removeprefix("data/"))) == expected, name
    for pool in ("train_core", "train_pool", "dev"):
        verify_expert_rows(manifest, assignment, pool, data.read(f"expert-{pool}.jsonl"))
    labels = 0
    for name in data.namelist():
        if name.startswith("dagger-") and name.endswith(".jsonl") and "/" not in name:
            rows = [json.loads(line) for line in io.TextIOWrapper(data.open(name), encoding="utf-8")]
            labels += verify_dagger_rows(manifest, rows, every)

    for key, entry in lock["adapters"].items():
        if entry.get("source") == "v0.4 lock":
            continue
        path = BUNDLE / "training" / f"{key}.json"
        training = read(path)
        best = min(training["epochs"], key=lambda e: e["dev_loss"])
        assert training["status"] == "completed", key
        assert best["checkpoint"] == training["selected_checkpoint"] == entry["checkpoint"], key
        assert best["adapter_sha256"] == entry["sha256"], key
        assert sha(path.read_bytes()) == entry["training_report_sha256"], key

    # Held-out dialects, then the multi arms on the study contract (each report names its contract).
    reports = [
        read(p) | {"_dir": d, "_file": p.stem}
        for d in ("test", "study-contract")
        for p in sorted((BUNDLE / d).glob("*.json"))
    ]
    assert all(
        r["contract"] == ("study" if r["_dir"] == "study-contract" else "assigned") for r in reports
    )

    def trace(report, row):
        archive = BUNDLE / "traces" / report["_dir"] / f"{report['_file']}.zip"
        return zipfile.ZipFile(archive).read(row["trace"])

    replayed = verify_reports(reports, trace, manifest, assignment, lock, replay_every)

    multi = BUNDLE / "study-contract"
    recomputed = analyze(
        BUNDLE / "test",
        ROOT / "artifacts/v0.4/test",
        manifest,
        assignment,
        multi if multi.exists() else None,
    )
    same(json.loads(json.dumps(recomputed)), read(BUNDLE / "analysis-test.json"))
    return labels, replayed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dagger-every", type=int, default=1, help="re-verify every Nth DAgger label")
    parser.add_argument("--replay-every", type=int, default=1, help="replay every Nth test episode")
    args = parser.parse_args()
    if not (BUNDLE / "test-lock.json").exists():
        print("No dialect study bundle yet (artifacts/v0.5): nothing to verify.")
    else:
        labels, replayed = verify(args.dagger_every, args.replay_every)
        print(
            f"Verified provenance, {labels} DAgger labels and {replayed} dialect test episode replays."
        )
