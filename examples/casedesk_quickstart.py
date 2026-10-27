"""CaseDesk in one minute, no GPU: a fault-injected episode, then a recorded failure replayed.

1. The scripted teacher solves one registered test episode over real HTTP while the service
   injects a 412 conflict and a 429 rate limit; the grader reads server state, not the claim.
2. Two recorded model runs on that same episode are replayed through a fresh server: a
   behaviour-cloning adapter that loops on a mis-copied ETag, and the DAgger adapter.

    python examples/casedesk_quickstart.py
"""

import json
import zipfile
from pathlib import Path

from resolvelab.casedesk.manifest import load_manifest
from resolvelab.casedesk.runner import run_episode

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts/v0.4"
EPISODE = "test-test_conflict_rate-07"


def show(trace, limit=8):
    for obs in trace["observations"][:limit]:
        args = {
            k: v for k, v in obs["arguments"].items() if k in ("cursor", "ticket_id", "etag", "seconds")
        }
        status = obs["result"].get("status", "-")
        print(f"    {obs['name']:<13} {json.dumps(args)[:64]:<66} -> {status}")
    hidden = len(trace["observations"]) - limit
    if hidden > 0:
        print(f"    ... {hidden} more calls")
    verdict = trace["verdict"]
    result = "PASS" if verdict["passed"] else f"FAIL ({verdict['failure_category']})"
    print(f"    grader: {result}; claim={verdict['claim']}, commits={verdict['commits']}\n")


def replay(arm, spec):
    """Re-execute a published model trace's actions against a fresh HTTP server."""
    report = json.loads((BUNDLE / "test" / f"{arm}.json").read_text(encoding="utf-8"))
    row = next(r for r in report["rows"] if r["spec_id"] == spec["id"])
    trace = json.loads(zipfile.ZipFile(BUNDLE / "traces/test" / f"{arm}.zip").read(row["trace"]))
    actions = [d["action"] for d in trace["decisions"] if "action" in d]
    again = run_episode(spec, forced=actions, max_tools=len(actions))
    assert again["observations"] == trace["observations"], "replay diverged from the recording"
    return again


def main():
    manifest = load_manifest(ROOT / "benchmarks/casedesk-v2.json")
    spec = next(s for s in manifest["episodes"]["test"] if s["id"] == EPISODE)
    print(
        f"Episode {spec['id']}: faults {spec['faults']}, {spec['n_records']} records, "
        f"target in slot {spec['target_pos']}\n"
    )
    teacher = run_episode(spec)
    print("  Task:", teacher["task"], "\n")
    print("  Scripted teacher (environment check, not a model):")
    show(teacher)
    print("  Recorded Qwen3-0.6B + behaviour cloning (bc-volume, seed 2026), replayed:")
    show(replay("bc-volume-2026", spec))
    print("  Recorded Qwen3-0.6B + DAgger (seed 2026), replayed:")
    show(replay("dagger-2026", spec))
    print("Full results: artifacts/v0.4/RESULTS.md")


if __name__ == "__main__":
    main()
