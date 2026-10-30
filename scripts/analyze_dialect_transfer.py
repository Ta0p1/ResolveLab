"""Run the registered dialect-transfer analysis. The test pool needs the lock to exist first."""

import argparse
import json
from pathlib import Path

from resolvelab.casedesk.manifest import load_manifest
from resolvelab.dialects.analysis import analyze, markdown
from resolvelab.dialects.assignment import load_assignment
from resolvelab.evaluation import write_report

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pool", choices=["dev", "test"])
    parser.add_argument(
        "--dialect-dir", type=Path, help="reports in dialects (default .local/v05/eval/<pool>)"
    )
    parser.add_argument(
        "--multi-study-dir", type=Path, help="multi arms evaluated on the study contract"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="writes <output>.json and <output>.md"
    )
    args = parser.parse_args()
    if args.pool == "test" and not (ROOT / "artifacts/v0.5/test-lock.json").exists():
        parser.error("No test lock: the test analysis runs only after a registered, locked test phase")
    manifest = load_manifest(ROOT / "benchmarks/casedesk-v2.json")
    assignment = load_assignment(ROOT / "benchmarks/casedesk-dialects-v1.json", manifest)
    dialect_dir = args.dialect_dir or ROOT / ".local/v05/eval" / args.pool
    study_dir = ROOT / "artifacts/v0.4" / args.pool
    report = analyze(dialect_dir, study_dir, manifest, assignment, args.multi_study_dir, args.pool)
    write_report(args.output.with_suffix(".json"), report)
    args.output.with_suffix(".md").write_text(markdown(report), encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {"transfer": {k: v["classification"] for k, v in report["transfer"].items()}}
            | {"decisions": report["decisions"]}
        )
    )


if __name__ == "__main__":
    main()
