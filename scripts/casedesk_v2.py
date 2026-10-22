"""CaseDesk v2 pipeline: expert data, DAgger rollouts, matched datasets, training, evaluation.

Every step writes new files and refuses to overwrite; the orchestrator
(`scripts/run_casedesk_v2.py`) skips steps whose outputs already exist.
"""

import argparse
import json
from pathlib import Path

from resolvelab.benchmark import digest
from resolvelab.casedesk.data import dagger_rows, expert_rows, subsample, validate_rows
from resolvelab.casedesk.evaluate import evaluate
from resolvelab.casedesk.manifest import load_manifest
from resolvelab.curation import read_rows
from resolvelab.evaluation import write_report
from resolvelab.httpdesk.benchmark import source_hash
from resolvelab.store import dumps, utcnow
from resolvelab.training import file_hash, train

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "benchmarks/casedesk-v2-study.json"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_rows(path, rows):
    path = Path(path)
    if path.exists():
        raise ValueError(f"{path} exists; data files are immutable")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n")
    return file_hash(path)


def model_config(study, model, **extra):
    return {**study["models"][model], **study["decoding"], **extra}


def collect_expert(manifest, pool, output):
    rows, episodes = expert_rows(manifest, pool)
    sha = write_rows(output, rows)
    write_report(
        Path(output).with_suffix(".provenance.json"),
        {
            "pool": pool,
            "manifest_sha256": digest(manifest),
            "source_sha256": source_hash(),
            "teacher": "casedesk_v2_offpolicy_teacher",
            "rows": len(rows),
            "sha256": sha,
            "episodes": episodes,
            "created_at": utcnow(),
        },
    )


def rollout(manifest, study, seed, adapter, output):
    from resolvelab.casedesk.policy import make_policy

    rows, episodes, metadata = [], [], {}
    for spec in study["dagger"]["rollouts"]:
        arm = model_config(study, "qwen3-0.6b")
        if "temperature" in spec:
            arm |= {"temperature": spec["temperature"], "sampling_seed": seed}
        provider = make_policy(arm, adapter)
        part, report = dagger_rows(manifest, study["dagger"]["pool"], provider, spec["name"])
        rows += part
        episodes += report
        metadata[spec["name"]] = provider.metadata
        del provider
        __import__("torch").cuda.empty_cache()
    sha = write_rows(output, rows)
    write_report(
        Path(output).with_suffix(".provenance.json"),
        {
            "seed": seed,
            "learner_adapter": str(adapter),
            "learner_adapter_sha256": file_hash(Path(adapter) / "adapter_model.safetensors"),
            "manifest_sha256": digest(manifest),
            "source_sha256": source_hash(),
            "rows": len(rows),
            "sha256": sha,
            "episodes": episodes,
            "models": metadata,
            "created_at": utcnow(),
        },
    )


def assemble(manifest, data, seed=None):
    """Without a seed: the shared bc set. With one: bc-volume-<seed> and dagger-<seed>, which
    add the same number of rows to the same expert core."""
    core = read_rows(data / "expert-train_core.jsonl")
    dev = read_rows(data / "expert-dev.jsonl")
    sets = {"bc": core}
    if seed is not None:
        pool = read_rows(data / "expert-train_pool.jsonl")
        dagger = read_rows(data / f"dagger-{seed}.jsonl")
        added = min(len(pool), len(dagger))
        sets = {
            f"bc-volume-{seed}": core + subsample(pool, added, seed),
            f"dagger-{seed}": core + subsample(dagger, added, seed),
        }
    summary = {}
    for name, rows in sets.items():
        directory = data / name
        if (directory / "train.jsonl").exists():
            continue
        validate_rows(rows, manifest, "train")
        validate_rows(dev, manifest, "dev")
        summary[name] = {
            "train_rows": len(rows),
            "train_sha256": write_rows(directory / "train.jsonl", rows),
            "dev_sha256": write_rows(directory / "dev.jsonl", dev),
            "origins": {o: sum(r["origin"] == o for r in rows) for o in ("expert", "dagger")},
        }
    print(json.dumps(summary, indent=1))


def train_arm(manifest, study, data, seed, output):
    config = {**study["training"], **study["models"]["qwen3-0.6b"], "seed": seed}
    report = train(
        config,
        manifest,
        data,
        output,
        row_validator=validate_rows,
        teacher="casedesk_v2_offpolicy_teacher",
        fingerprint=source_hash,
    )
    print(json.dumps({k: report[k] for k in ("selected_checkpoint", "examples", "wall_seconds")}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["collect-expert", "rollout", "assemble", "train", "eval"])
    parser.add_argument("--pool")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--data", type=Path, default=Path(".local/v04/data"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--arm")
    parser.add_argument("--model", default="qwen3-0.6b")
    parser.add_argument("--thinking", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    study = read(STUDY)
    manifest = load_manifest(ROOT / study["manifest"])
    if args.seed is not None and args.seed not in study["training_seeds"]:
        parser.error("Seed not registered")
    if args.command == "collect-expert":
        collect_expert(manifest, args.pool, args.output)
    elif args.command == "rollout":
        rollout(manifest, study, args.seed, args.adapter, args.output)
    elif args.command == "assemble":
        assemble(manifest, args.data, args.seed)
    elif args.command == "train":
        train_arm(manifest, study, args.data, args.seed, args.output)
    else:
        from resolvelab.casedesk.policy import make_policy

        arm = model_config(
            study,
            args.model,
            name=args.arm,
            seed=args.seed,
            adapter=str(args.adapter) if args.adapter else None,
        )
        if args.thinking:
            arm["thinking_budget"] = args.thinking
            arm["sampling_seed"] = 0
        provider = make_policy(arm, args.adapter)
        report = evaluate(manifest, args.pool, arm, args.output, provider, args.resume, args.limit)
        print(json.dumps(report["summary"], indent=1))


if __name__ == "__main__":
    main()
