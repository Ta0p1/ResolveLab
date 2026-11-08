"""Milestone-2 parity: CaseDesk behind the fault proxy reproduces grader v2's published verdicts.

For every published v0.4 test episode in scope (no actor faults; see
``resolvelab.proxy.casedesk``), the recorded actions are replayed through the proxy in front of
an unchanged CaseDesk service whose HTTP faults are off. The proxy injects the faults and its
declarative rules grade the log. Each verdict (pass, and failure category) is compared with
the one grader v2 published. GPU-free, over real HTTP.

    python scripts/check_proxy_parity.py                 # every in-scope episode of every arm
    python scripts/check_proxy_parity.py --every 40      # a thinned sample, as in CI
    python scripts/check_proxy_parity.py --output parity.json

Exits 1 if any verdict disagrees.
"""

import argparse
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

from resolvelab.casedesk.manifest import load_manifest
from resolvelab.proxy.casedesk import in_scope, replay_actions

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts" / "v0.4"


def published_episodes(every=1, arms=None):
    """(arm, spec_id, recorded actions, published verdict) for the in-scope test episodes."""
    manifest = load_manifest(ROOT / "benchmarks" / "casedesk-v2.json")
    specs = {spec["id"]: spec for spec in manifest["episodes"]["test"]}
    index = 0
    for report_path in sorted((BUNDLE / "test").glob("*.json")):
        arm = report_path.stem
        if arms and arm not in arms:
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        traces = zipfile.ZipFile(BUNDLE / "traces" / "test" / f"{arm}.zip")
        for row in report["rows"]:
            spec = specs[row["spec_id"]]
            if not in_scope(spec):
                continue
            index += 1
            if (index - 1) % every:
                continue
            trace = json.loads(traces.read(row["trace"]))
            actions = [d["action"] for d in trace["decisions"] if "action" in d]
            yield arm, spec, actions, trace["verdict"]


def check(every=1, arms=None, progress=False):
    rows = []
    for arm, spec, actions, published in published_episodes(every, arms):
        verdict = replay_actions(spec, actions).verdict()
        rows.append(
            {
                "arm": arm,
                "spec_id": spec["id"],
                "composition": spec["composition"],
                "published": {"passed": published["passed"], "category": published["failure_category"]},
                "proxy": {"passed": verdict["passed"], "category": verdict["failure_category"]},
                "agree": verdict["passed"] == published["passed"]
                and verdict["failure_category"] == published["failure_category"],
                "failed_checks": [c["rule"] for c in verdict["checks"] if c["passed"] is False],
            }
        )
        if progress and len(rows) % 50 == 0:
            print(f"  {len(rows)} episodes replayed", file=sys.stderr, flush=True)
    return rows


def table(rows, key):
    total, agree = Counter(), Counter()
    for row in rows:
        total[row[key]] += 1
        agree[row[key]] += row["agree"]
    return {name: [agree[name], total[name]] for name in sorted(total)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--every", type=int, default=1, help="replay every Nth in-scope episode")
    parser.add_argument("--arm", action="append", help="only these arms (report names)")
    parser.add_argument("--output", type=Path, help="write every row and the tables as JSON")
    args = parser.parse_args()
    rows = check(args.every, set(args.arm or ()), progress=True)
    by_arm, by_composition = table(rows, "arm"), table(rows, "composition")
    published = Counter(r["published"]["passed"] for r in rows)
    print(f"{'arm':<20} agree / episodes")
    for name, (agree, total) in by_arm.items():
        print(f"{name:<20} {agree:>5} / {total}")
    print(f"\n{'composition':<26} agree / episodes")
    for name, (agree, total) in by_composition.items():
        print(f"{name:<26} {agree:>5} / {total}")
    disagreements = [r for r in rows if not r["agree"]]
    print(
        f"\n{sum(r['agree'] for r in rows)} / {len(rows)} verdicts agree "
        f"({published[True]} published passes, {published[False]} failures)"
    )
    for row in disagreements:
        print(
            f"  {row['arm']} {row['spec_id']}: published {row['published']}, "
            f"proxy {row['proxy']}, failed checks {row['failed_checks']}"
        )
    if args.output:
        summary = {"arms": by_arm, "compositions": by_composition, "rows": rows}
        args.output.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return 1 if disagreements else 0


if __name__ == "__main__":
    sys.exit(main())
