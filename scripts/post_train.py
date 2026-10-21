"""Run from the repository root. See docs/post-training.md for the frozen protocol."""

import argparse
import json
from pathlib import Path

from resolvelab.benchmark import load_manifest
from resolvelab.curation import collect
from resolvelab.evaluation import write_report
from resolvelab.experiments import compare, evaluate_compositions
from resolvelab.training import train


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["collect", "train", "eval", "compare"])
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/composition-v1.json"))
    parser.add_argument("--config", type=Path, default=Path("benchmarks/sft-v1.json"))
    parser.add_argument("--data", type=Path, default=Path(".local/sft-data"))
    parser.add_argument("--output", type=Path, default=Path(".local/sft-v1"))
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--reference", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--base-report", type=Path)
    parser.add_argument("--sft-report", type=Path)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.command == "collect":
        result = collect(manifest, args.data, args.data)
    elif args.command == "train":
        result = train(config, manifest, args.data, args.output)
    elif args.command == "eval":
        result = evaluate_compositions(
            manifest,
            config,
            args.split,
            args.output,
            args.data,
            args.adapter,
            args.reference,
            args.resume,
        )
    else:
        result = compare(
            json.loads(args.base_report.read_text(encoding="utf-8")),
            json.loads(args.sft_report.read_text(encoding="utf-8")),
        )
        write_report(args.output, result)
    print(json.dumps({k: v for k, v in result.items() if k not in {"steps", "splits"}}, indent=2))


if __name__ == "__main__":
    main()
