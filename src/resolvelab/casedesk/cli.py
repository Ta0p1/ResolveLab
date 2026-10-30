"""``resolvelab casedesk``: list registered episodes, run one, or evaluate a model on a pool.

    resolvelab casedesk episodes --pool dev
    resolvelab casedesk run --episode test-test_conflict_rate-07 --model ollama:qwen3:4b
    resolvelab casedesk eval --pool dev --model anthropic:claude-opus-5-5 --output dev.json

Reports are resumable and identity-checked (``casedesk.evaluate``); traces are written next
to them, one JSON file per episode.
"""

import argparse
import json
import sys
from pathlib import Path

from ..providers import make_provider
from .evaluate import evaluate
from .manifest import load_manifest
from .runner import run_episode

MANIFEST = Path(__file__).resolve().parents[3] / "benchmarks/casedesk-v2.json"
POOLS = ["train_core", "train_pool", "dev", "test"]


def parse_options(pairs):
    options = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise SystemExit(f"--option expects KEY=VALUE, got {pair!r}")
        options[key] = value
    return options


def show(trace, out=None):
    out = out or sys.stdout  # resolved per call, so redirected stdout is honoured
    for obs in trace["observations"]:
        args = {
            k: v for k, v in obs["arguments"].items() if k in ("cursor", "ticket_id", "etag", "seconds")
        }
        print(
            f"  {obs['name']:<13} {json.dumps(args)[:70]:<72} -> {obs['result'].get('status', '-')}",
            file=out,
        )
    for decision in trace["decisions"]:
        if "error" in decision:
            print(f"  [no action: {decision['error'][:120]}]", file=out)
    verdict = trace["verdict"]
    outcome = "PASS" if verdict["passed"] else f"FAIL ({verdict['failure_category']})"
    tokens = sum(d.get("usage", {}).get("output_tokens", 0) for d in trace["decisions"])
    print(
        f"  grader: {outcome}; claim={verdict['claim']}, commits={verdict['commits']}, "
        f"tools={len(trace['observations'])}, output tokens={tokens}",
        file=out,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(prog="resolvelab casedesk", description=__doc__.split("\n")[0])
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("episodes", help="List registered episodes in a pool")
    listing.add_argument("--pool", choices=POOLS, default="test")
    one = sub.add_parser("run", help="Run one registered episode and print its trace")
    one.add_argument("--episode", required=True)
    one.add_argument("--model", default="teacher", help="provider:model, e.g. ollama:qwen3:4b")
    one.add_argument("--option", action="append", default=[], metavar="KEY=VALUE")
    one.add_argument("--json", action="store_true", help="print the whole trace as JSON")
    many = sub.add_parser("eval", help="Evaluate a model on a pool (resumable)")
    many.add_argument("--pool", choices=["dev", "test"], required=True)
    many.add_argument("--model", required=True, help="provider:model, e.g. anthropic:claude-opus-5-5")
    many.add_argument("--option", action="append", default=[], metavar="KEY=VALUE")
    many.add_argument("--output", type=Path, required=True)
    many.add_argument("--limit", type=int)
    many.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest)

    if args.command == "episodes":
        for spec in manifest["episodes"][args.pool]:
            print(
                f"{spec['id']:<44} faults={'+'.join(spec['faults']) or '-':<32} "
                f"records={spec['n_records']} slot={spec['target_pos']} wording={spec['phrasing']}"
            )
        return 0

    provider, arm = make_provider(args.model, parse_options(args.option))
    if args.command == "run":
        specs = {s["id"]: s for rows in manifest["episodes"].values() for s in rows}
        if args.episode not in specs:
            raise SystemExit(f"Unknown episode {args.episode!r}; see `resolvelab casedesk episodes`")
        trace = run_episode(specs[args.episode], provider, max_tools=arm["max_tools"])
        trace.pop("steps")
        if args.json:
            print(json.dumps(trace, indent=1, default=str))
        else:
            print(f"{args.episode} with {args.model}\n  task: {trace['task']}")
            show(trace)
        return 0 if trace["verdict"]["passed"] else 1

    if args.pool == "test":
        print(
            "Note: the v0.4 test pool is public. A new model's score on it is a post-hoc "
            "measurement, not a fresh held-out result.",
            file=sys.stderr,
        )
    report = evaluate(manifest, args.pool, arm, args.output, provider, args.resume, args.limit)
    summary = report["summary"]
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "episodes",
                    "passed",
                    "success_rate",
                    "wilson_95",
                    "unsafe_mutations",
                    "false_successes",
                    "spurious_escalations",
                    "located_target",
                    "failure_categories",
                    "output_tokens",
                    "input_tokens",
                )
            },
            indent=1,
        )
    )
    return 0
