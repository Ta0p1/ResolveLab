"""Apply the registered v2 analysis to one pool's completed reports."""

import argparse
import json
from pathlib import Path

from resolvelab.casedesk.analysis import analyze, markdown
from resolvelab.casedesk.manifest import load_manifest
from resolvelab.evaluation import write_report

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pool", choices=["dev", "test"])
    parser.add_argument("--reports", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    study = json.loads((ROOT / "benchmarks/casedesk-v2-study.json").read_text(encoding="utf-8"))
    manifest = load_manifest(ROOT / study["manifest"])
    reports = args.reports or ROOT / ".local/v04/eval" / args.pool
    result = analyze(reports, manifest, args.pool)
    write_report(args.output.with_suffix(".json"), result)
    args.output.with_suffix(".md").write_text(markdown(result), encoding="utf-8", newline="\n")
    print(markdown(result))


if __name__ == "__main__":
    main()
