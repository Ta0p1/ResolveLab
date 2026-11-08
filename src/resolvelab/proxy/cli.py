"""``resolvelab proxy``: run, serve, grade and replay fault-proxy episodes.

    resolvelab proxy run scenario.yaml --model ollama:qwen3:4b --log refund.jsonl
    resolvelab proxy serve scenario.yaml --port 8899 --log refund.jsonl
    resolvelab proxy grade refund.jsonl
    resolvelab proxy replay refund.jsonl

``run`` drives one episode with a model (any provider spec except the CaseDesk-only
``teacher`` and ``hf``) and writes the log and a report with the verdict. ``serve`` starts the
proxy for an agent in its own process and stops when the agent posts ``/_resolvelab/finish``
(or on Ctrl-C). ``grade`` grades a log; ``replay`` re-runs one against the service, which must
first be reset to the state the log started from.
"""

import argparse
import json
import sys
from pathlib import Path

from ..providers import make_provider, parse_spec
from .agent import ModelAgent
from .episode import replay, run_episode, serve
from .grading import grade
from .log import read_log
from .scenario import Scenario, ScenarioError, load_scenario


def pairs(values, flag):
    options = {}
    for pair in values:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise SystemExit(f"{flag} expects KEY=VALUE, got {pair!r}")
        options[key] = value
    return options


def summary(verdict, out=None):
    out = out or sys.stdout
    outcome = "PASS" if verdict["passed"] else f"FAIL ({verdict['failure_category']})"
    print(
        f"{verdict['scenario']} seed={verdict['seed']}: {outcome}; claim={verdict['claim']}, "
        f"expected={verdict['expected_outcome']}, requests={verdict['requests']}, "
        f"commits={verdict['commits']}, faults={json.dumps(verdict['faults'])}",
        file=out,
    )
    for check in verdict["checks"]:
        mark = {True: "ok", False: "FAIL", None: "skip"}[check["passed"]]
        detail = ""
        if check["rule"] == "allowed_changes" and check["violations"]:
            detail = ", ".join(f"{c['resource']}:{c['field'] or '*'}" for c in check["violations"])
        elif check["rule"] == "expected_state" and check["passed"] is False:
            detail = ", ".join(
                f"{f['resource']}.{f['field']}={f['actual']!r} (want {f['expected']!r})"
                for f in check["fields"]
                if not f["passed"]
            )
        elif check["rule"] == "exactly_once":
            detail = f"{check['path']}: {check['commits']} commits, {check['distinct_keys']} keys"
        elif check["rule"] == "outcome":
            detail = f"claim={check['claim']} expected={check['expected']}"
        print(f"  {mark:<4} {check['rule']:<16} {detail}", file=out)


def scenario_of(args):
    try:
        return load_scenario(args.scenario, params=pairs(args.param, "--param"), upstream=args.upstream)
    except (ScenarioError, OSError) as exc:
        raise SystemExit(f"Scenario {args.scenario}: {exc}") from exc


def default_log(scenario, seed):
    return Path(f"{scenario.name}-seed{seed}.jsonl")


def command_run(args):
    try:
        provider_name, _ = parse_spec(args.model)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if provider_name in ("teacher", "hf"):
        raise SystemExit(
            f"{provider_name} is CaseDesk-specific (a scripted runbook or its constrained decoder); "
            "use an ollama:, openai: or anthropic: model, or serve the proxy to your own agent"
        )
    scenario = scenario_of(args)
    provider, arm = make_provider(args.model, pairs(args.option, "--option"))
    agent = ModelAgent(provider, args.max_steps or scenario.max_steps)
    log = args.log or default_log(scenario, args.seed)
    print(f"{scenario.name} with {args.model}\n  task: {scenario.task}", file=sys.stderr)
    try:
        episode = run_episode(
            scenario,
            lambda client, task: agent(client, task, scenario.api),
            seed=args.seed,
            log_path=log,
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    verdict = episode.verdict()
    report = {
        "verdict": verdict,
        "arm": arm,
        "provider": getattr(provider, "metadata", None),
        "agent_error": agent.error,
        "decisions": agent.decisions,
        "log": str(log),
    }
    report_path = Path(log).with_suffix(".report.json")
    report_path.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    if args.json:
        print(json.dumps(verdict, indent=1))
    else:
        summary(verdict)
        print(f"  log: {log}\n  report: {report_path}")
    return 0 if verdict["passed"] else 1


def command_serve(args):
    scenario = scenario_of(args)
    log = args.log or default_log(scenario, args.seed)

    def ready(url):
        prefix = scenario.control_prefix
        print(f"Proxy for {scenario.name} (seed {args.seed}) at {url}", flush=True)
        print(f"  upstream: {scenario.upstream}\n  task: {scenario.task}", flush=True)
        print(
            f'  wait:   POST {url}{prefix}/wait {{"seconds": n}}\n'
            f'  finish: POST {url}{prefix}/finish {{"outcome": "resolved" | "escalated"}}',
            flush=True,
        )

    try:
        episode = serve(
            scenario, seed=args.seed, log_path=log, host=args.host, port=args.port, ready=ready
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Episode ended ({episode.records[-1]['reason']}); log: {log}")
    print(f"Grade it with: resolvelab proxy grade {log}")
    return 0


def command_grade(args):
    try:
        records = read_log(args.log)
        scenario = None
        if args.scenario:
            header = Scenario(records[0]["scenario"])
            scenario = load_scenario(args.scenario, params=header.params, upstream=header.upstream)
        verdict = grade(records, scenario)
    except (ScenarioError, ValueError, OSError) as exc:
        raise SystemExit(f"{args.log}: {exc}") from exc
    if args.json:
        print(json.dumps(verdict, indent=1))
    else:
        summary(verdict)
    return 0 if verdict["passed"] else 1


def command_replay(args):
    try:
        result = replay(args.log, upstream=args.upstream)
    except (ScenarioError, ValueError, OSError, RuntimeError) as exc:
        raise SystemExit(f"{args.log}: {exc}") from exc
    if args.json:
        result = {k: v for k, v in result.items() if k != "records"}
        print(json.dumps(result, indent=1))
    else:
        same = result["verdict"] == result["logged_verdict"]
        print(
            f"replay: {'identical' if result['identical'] else 'DIFFERS'}; verdict {'same' if same else 'DIFFERS'}"
        )
        for mismatch in result["mismatches"]:
            print(f"  record {mismatch['index']}: logged {json.dumps(mismatch.get('logged'))[:160]}")
            print(
                f"  {' ' * len(str(mismatch['index']))}        replayed {json.dumps(mismatch.get('replayed'))[:160]}"
            )
        summary(result["verdict"])
    return 0 if result["identical"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="resolvelab proxy", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def episode_options(p):
        p.add_argument("scenario", type=Path, help="scenario file (.yaml, .yml or .json)")
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
        p.add_argument("--upstream", help="override the scenario's upstream URL")
        p.add_argument("--log", type=Path, help="episode log path (default: <name>-seed<seed>.jsonl)")

    run = sub.add_parser("run", help="Run one episode with a model and grade it")
    episode_options(run)
    run.add_argument("--model", required=True, help="provider:model, e.g. ollama:qwen3:4b")
    run.add_argument("--option", action="append", default=[], metavar="KEY=VALUE")
    run.add_argument("--max-steps", type=int, help="action budget (default: the scenario's)")
    run.add_argument("--json", action="store_true", help="print the verdict as JSON")

    srv = sub.add_parser("serve", help="Serve the proxy to an agent in its own process")
    episode_options(srv)
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8899)

    grd = sub.add_parser("grade", help="Grade an episode log")
    grd.add_argument("log", type=Path)
    grd.add_argument("--scenario", type=Path, help="re-grade under this scenario's rules")
    grd.add_argument("--json", action="store_true")

    rep = sub.add_parser("replay", help="Re-run a logged episode and compare every record")
    rep.add_argument("log", type=Path)
    rep.add_argument("--upstream", help="override the logged upstream URL")
    rep.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    commands = {
        "run": command_run,
        "serve": command_serve,
        "grade": command_grade,
        "replay": command_replay,
    }
    return commands[args.command](args)
