"""Reproduce CaseDesk data, training, evaluations and paired comparisons."""

import argparse
import json
from pathlib import Path

from resolvelab.evaluation import write_report
from resolvelab.httpdesk.benchmark import load_manifest, source_hash, validate_rows
from resolvelab.httpdesk.experiment import collect, compare, evaluate
from resolvelab.training import train


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["collect", "train", "eval", "compare"])
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/httpdesk-v1.json"))
    parser.add_argument("--config", type=Path, default=Path("benchmarks/httpdesk-sft-v1.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=Path(".local/http-data"))
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--reference", action="store_true")
    parser.add_argument("--larger", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--base-report", type=Path)
    parser.add_argument("--sft-report", type=Path)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.seed is not None:
        if args.seed not in config["training_seeds"]:
            parser.error("Seed not preregistered")
        config["seed"] = args.seed
    if args.larger:
        config.update(config["larger_baseline"])
    if args.command == "collect":
        result = collect(manifest, args.output)
    elif args.command == "train":
        result = train(
            config,
            manifest,
            args.data,
            args.output,
            row_validator=validate_rows,
            teacher="scripted_http_runbook_v1",
            fingerprint=source_hash,
        )
    elif args.command == "eval":
        result = evaluate(
            manifest, config, args.split, args.output, args.adapter, args.reference, args.resume
        )
    else:
        if not args.base_report or not args.sft_report:
            parser.error("compare requires --base-report and --sft-report")
        result = compare(
            json.loads(args.base_report.read_text(encoding="utf-8")),
            json.loads(args.sft_report.read_text(encoding="utf-8")),
        )
        write_report(args.output, result)
    print(
        json.dumps({k: v for k, v in result.items() if k not in {"steps", "rows", "splits"}}, indent=2)
    )


if __name__ == "__main__":
    main()
