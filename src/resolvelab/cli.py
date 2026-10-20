import argparse
import json
import sys
from pathlib import Path

from .evaluation import evaluate, export_trace, new_report
from .runner import Runner
from .scenarios import BY_ID
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="ResolveLab: run, verify, compare.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the local workbench")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--data-dir", default=".local")
    run = sub.add_parser("run", help="Execute one scenario")
    run.add_argument("--scenario", choices=BY_ID, default="lost_response")
    run.add_argument("--policy", choices=["naive", "reference", "ollama"], default="reference")
    run.add_argument("--model", default="qwen3:4b")
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--data-dir", default=".local")
    ev = sub.add_parser("eval", help="Execute the reproducible regression suite")
    ev.add_argument(
        "--policies", nargs="+", choices=["naive", "reference", "ollama"], default=["naive", "reference"]
    )
    ev.add_argument("--scenarios", nargs="+", choices=BY_ID, default=list(BY_ID))
    ev.add_argument("--seeds", nargs="+", type=int, default=[42])
    ev.add_argument("--model", default="qwen3:4b")
    ev.add_argument("--output", default="artifacts/evaluation.json")
    ev.add_argument("--data-dir", default=".local")
    ev.add_argument(
        "--require-policy",
        choices=["naive", "reference", "ollama"],
        help="Exit nonzero unless every episode of this policy passes",
    )
    export = sub.add_parser("export", help="Export a recorded trajectory as JSONL")
    export.add_argument("run_id")
    export.add_argument("--output", required=True)
    export.add_argument("--data-dir", default=".local")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(args.data_dir), host="127.0.0.1", port=args.port)
        return
    store = Store(Path(args.data_dir) / "resolvelab.sqlite")
    runner = Runner(store)
    if args.command == "run":
        result = runner.execute(store.create(args.scenario, args.seed, args.policy, args.model))
        print(
            json.dumps({k: result[k] for k in ("id", "status", "verdict", "summary", "error")}, indent=2)
        )
        sys.exit(0 if result["verdict"]["passed"] else 1)
    if args.command == "export":
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(export_trace(store, args.run_id), encoding="utf-8")
        print(args.output)
        return
    report = new_report(list(dict.fromkeys(args.policies)), args.scenarios, args.seeds, args.model)
    result = evaluate(runner, report, Path(args.output), args.model)
    print(
        json.dumps(
            {"status": result["status"], "summary": result["summary"], "report": args.output}, indent=2
        )
    )
    if result["status"] != "completed":
        sys.exit(1)
    if args.require_policy:
        summary = next((s for s in result["summary"] if s["policy"] == args.require_policy), None)
        if not summary or summary["pass_rate"] != 1:
            sys.exit(1)
