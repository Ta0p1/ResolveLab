"""GPU check: in the canonical dialect, DialectPolicy reproduces published v0.4 dev traces exactly.

Q1 of the dialect protocol compares a v0.4 adapter's published runs (the v0.3 decoder) with its
runs through DialectPolicy. That comparison is only about the contract if the two decoders are
the same function. This replays the first ``--limit`` dev episodes of a published v0.4 arm
with DialectPolicy in the canonical dialect and requires identical raw model outputs,
observations and verdicts. Dev only; it never touches the test pool or a held-out dialect.

    python scripts/check_dialect_decoder.py --arm dagger-42 --limit 5
"""

import argparse
import json
import zipfile
from pathlib import Path

from resolvelab.casedesk.manifest import load_manifest
from resolvelab.dialects import CANONICAL, run_dialect_episode
from resolvelab.dialects.policy import DialectPolicy
from resolvelab.training import file_hash

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts/v0.4"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", default="dagger-42", help="a published v0.4 dev report name")
    parser.add_argument("--adapters", type=Path, default=ROOT / ".local/v04/runs")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    report = json.loads((BUNDLE / "dev" / f"{args.arm}.json").read_text(encoding="utf-8"))
    lock = json.loads((BUNDLE / "test-lock.json").read_text(encoding="utf-8"))
    adapter = args.adapters / args.arm / lock["adapters"][args.arm]["checkpoint"]
    if file_hash(adapter / "adapter_model.safetensors") != report["adapter_sha256"]:
        raise SystemExit(f"{adapter} is not the adapter behind the published {args.arm} dev report")
    manifest = load_manifest(ROOT / "benchmarks/casedesk-v2.json")
    specs = {s["id"]: s for s in manifest["episodes"]["dev"]}
    config = {k: v for k, v in report["arm"].items() if k not in ("name", "seed", "adapter")}
    policy = DialectPolicy(config, adapter)
    traces = zipfile.ZipFile(BUNDLE / "traces" / "dev" / f"{args.arm}.zip")
    identical = 0
    for row in report["rows"][: args.limit]:
        published = json.loads(traces.read(row["trace"]))
        ours = run_dialect_episode(
            specs[row["spec_id"]], CANONICAL, policy, max_tools=config["max_tools"]
        )
        outputs = [
            [d.get("usage", {}).get("raw_output") for d in t["decisions"]] for t in (published, ours)
        ]
        same = (
            outputs[0] == outputs[1]
            and ours["observations"] == published["observations"]
            and ours["verdict"] == published["verdict"]
        )
        identical += same
        print(
            json.dumps({"spec_id": row["spec_id"], "identical": same, "actions": len(outputs[1])}),
            flush=True,
        )
    print(
        f"{identical}/{min(args.limit, len(report['rows']))} episodes identical to the published {args.arm} dev traces"
    )
    if identical != min(args.limit, len(report["rows"])):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
