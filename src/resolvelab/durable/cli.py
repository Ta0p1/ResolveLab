"""``resolvelab durable``: CaseDesk on a persisted store, with crashes, restarts and races.

    resolvelab durable episodes
    resolvelab durable run --episode durable-crash_after-00
    resolvelab durable run --episode durable-crash_after-00 --policy new_key_retry
    resolvelab durable run --episode durable-restart-00 --store process
    resolvelab durable suite
    resolvelab durable race

``run`` exits 0 when the durable grader passes the episode; ``suite`` runs the teacher on every
episode and exits 0 only if all pass; ``race`` exits 0 when each race case committed once.
"""

import argparse
import json
import sys
from pathlib import Path

from ..casedesk.cli import parse_options, show
from ..casedesk.teacher import teacher_next
from ..providers import make_provider
from .counterexamples import COUNTEREXAMPLES, stale_etag_retry
from .episodes import EXPERIMENT, build_episodes
from .race import race
from .runner import run_durable_episode
from .store import STORES

POLICIES = {"teacher": teacher_next, **COUNTEREXAMPLES, "stale_etag_retry": stale_etag_retry}


def summary(verdict):
    keys = (
        "commits",
        "duplicate_key_commits",
        "lost_acknowledged_commits",
        "restarts",
        "fresh_after_restart",
        "v2_passed",
    )
    return ", ".join(f"{key}={verdict[key]}" for key in keys)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="resolvelab durable", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("episodes", help=f"List the {EXPERIMENT} episodes")
    one = sub.add_parser("run", help="Run one episode and print its trace")
    one.add_argument("--episode", required=True)
    one.add_argument("--policy", choices=sorted(POLICIES), default="teacher")
    one.add_argument("--model", help="provider:model instead of a scripted policy, e.g. ollama:qwen3:4b")
    one.add_argument("--option", action="append", default=[], metavar="KEY=VALUE")
    one.add_argument("--store", choices=STORES, default="durable")
    one.add_argument("--keep", type=Path, help="keep the episode's store, ledger and worker logs here")
    one.add_argument("--json", action="store_true", help="print the whole trace as JSON")
    suite = sub.add_parser("suite", help="Run the teacher on every episode")
    suite.add_argument("--store", choices=STORES, default="durable")
    races = sub.add_parser("race", help="Concurrent PATCHes to two workers on one store")
    races.add_argument("--store", choices=STORES, default="durable")
    races.add_argument("--hold-ms", type=int, default=200)
    args = parser.parse_args(argv)
    specs = {spec["id"]: spec for spec in build_episodes()}

    if args.command == "episodes":
        for spec in specs.values():
            print(
                f"{spec['id']:<36} faults={'+'.join(spec['faults']):<42} workers={spec['workers']} "
                f"records={spec['n_records']} slot={spec['target_pos']}"
            )
        return 0

    if args.command == "run":
        if args.episode not in specs:
            raise SystemExit(f"Unknown episode {args.episode!r}; see `resolvelab durable episodes`")
        # The "teacher" spec yields no provider, so the scripted --policy acts.
        provider, arm = make_provider(args.model or "teacher", parse_options(args.option))
        label = args.model or args.policy
        trace = run_durable_episode(
            specs[args.episode],
            provider,
            policy=POLICIES[args.policy],
            max_tools=arm["max_tools"],
            store=args.store,
            directory=args.keep,
        )
        if args.json:
            print(json.dumps(trace, indent=1, default=str))
        else:
            print(f"{args.episode} with {label} on the {args.store} store\n  task: {trace['task']}")
            show(trace)
            print(f"  durable: {summary(trace['verdict'])}")
            if args.keep:
                print(f"  store kept in {args.keep}")
        return 0 if trace["verdict"]["passed"] else 1

    if args.command == "suite":
        failed = 0
        for spec in specs.values():
            verdict = run_durable_episode(spec, store=args.store)["verdict"]
            failed += not verdict["passed"]
            outcome = "PASS" if verdict["passed"] else f"FAIL ({verdict['failure_category']})"
            print(f"{spec['id']:<36} {outcome:<34} {summary(verdict)}", flush=True)
        print(f"{len(specs) - failed}/{len(specs)} passed on the {args.store} store")
        return 0 if failed == 0 else 1

    ok = True
    for case in ("same_key", "new_keys", "key_reuse"):
        responses, snapshot = race(case, store=args.store, hold_ms=args.hold_ms)
        statuses = sorted(r["status"] for r in responses)
        workers = sorted({e["boot"] for e in snapshot.http_events if e["method"] == "PATCH"})
        once = len(snapshot.commits) == 1
        ok &= once
        print(
            f"{case:<10} responses={statuses} commits={len(snapshot.commits)} "
            f"served_by_boots={workers} {'exactly once' if once else 'NOT exactly once'}"
        )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
