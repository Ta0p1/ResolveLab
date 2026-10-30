"""Dialect transfer pipeline (draft protocol): expert rows, DAgger rollouts, sets, training, eval.

Mirrors ``scripts/casedesk_v2.py`` with every episode in its assigned dialect. Models,
decoding, LoRA hyperparameters, seeds and the DAgger rollout plan are read from the v0.4
study configuration, unchanged. Every step writes new files and refuses to overwrite.

    python scripts/dialect_transfer.py collect-expert --pool train_core --output .local/v05/data/expert-train_core.jsonl
    python scripts/dialect_transfer.py eval --pool dev --arm teacher --output .local/v05/eval/dev/teacher.json
"""

import argparse
import json
from functools import partial
from pathlib import Path

from resolvelab.benchmark import digest
from resolvelab.casedesk.data import subsample
from resolvelab.casedesk.manifest import load_manifest
from resolvelab.curation import read_rows
from resolvelab.dialects.assignment import load_assignment
from resolvelab.dialects.data import dagger_rows, expert_rows, validate_rows
from resolvelab.dialects.evaluate import evaluate
from resolvelab.evaluation import write_report
from resolvelab.httpdesk.benchmark import source_hash
from resolvelab.store import dumps, utcnow
from resolvelab.training import file_hash, train

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "benchmarks/casedesk-v2-study.json"
ASSIGNMENT = ROOT / "benchmarks/casedesk-dialects-v1.json"
TEACHER = "casedesk_v2_offpolicy_teacher_in_dialects"


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


def provenance(manifest, assignment, **extra):
    return {
        "manifest_sha256": digest(manifest),
        "assignment_sha256": digest(assignment),
        "source_sha256": source_hash(),
        "teacher": TEACHER,
        **extra,
        "created_at": utcnow(),
    }


def collect_expert(manifest, assignment, pool, output, limit=None):
    rows, episodes = expert_rows(manifest, assignment, pool, limit)
    sha = write_rows(output, rows)
    report = provenance(manifest, assignment, pool=pool, rows=len(rows), sha256=sha, episodes=episodes)
    write_report(Path(output).with_suffix(".provenance.json"), report)


def rollout(manifest, assignment, study, seed, adapter, output, limit=None):
    from resolvelab.dialects.policy import DialectPolicy

    rows, episodes, metadata = [], [], {}
    for spec in study["dagger"]["rollouts"]:
        temperature = spec.get("temperature")
        policy = DialectPolicy(
            model_config(study, "qwen3-0.6b"),
            adapter,
            temperature=temperature,
            seed=seed if temperature else 0,
        )
        part, report = dagger_rows(
            manifest, assignment, study["dagger"]["pool"], policy, spec["name"], limit
        )
        rows += part
        episodes += report
        metadata[spec["name"]] = policy.metadata
        del policy
        __import__("torch").cuda.empty_cache()
    sha = write_rows(output, rows)
    report = provenance(
        manifest,
        assignment,
        seed=seed,
        learner_adapter=str(adapter),
        learner_adapter_sha256=file_hash(Path(adapter) / "adapter_model.safetensors"),
        rows=len(rows),
        sha256=sha,
        episodes=episodes,
        models=metadata,
    )
    write_report(Path(output).with_suffix(".provenance.json"), report)


def assemble(manifest, assignment, data, seed=None):
    """Without a seed: bc-multi. With one: bc-volume-multi-<seed> and dagger-multi-<seed>, which
    add the same number of rows to the same expert core (the v0.4 size-match rule)."""
    core = read_rows(data / "expert-train_core.jsonl")
    dev = read_rows(data / "expert-dev.jsonl")
    sets = {"bc-multi": core}
    if seed is not None:
        pool = read_rows(data / "expert-train_pool.jsonl")
        dagger = read_rows(data / f"dagger-{seed}.jsonl")
        added = min(len(pool), len(dagger))
        sets = {
            f"bc-volume-multi-{seed}": core + subsample(pool, added, seed),
            f"dagger-multi-{seed}": core + subsample(dagger, added, seed),
        }
    summary = {}
    for name, rows in sets.items():
        directory = data / name
        if (directory / "train.jsonl").exists():
            continue
        validate_rows(rows, manifest, "train", assignment)
        validate_rows(dev, manifest, "dev", assignment)
        summary[name] = {
            "train_rows": len(rows),
            "train_sha256": write_rows(directory / "train.jsonl", rows),
            "dev_sha256": write_rows(directory / "dev.jsonl", dev),
            "origins": {o: sum(r["origin"] == o for r in rows) for o in ("expert", "dagger")},
        }
    print(json.dumps(summary, indent=1))


def train_arm(manifest, assignment, study, data, seed, output):
    config = {**study["training"], **study["models"]["qwen3-0.6b"], "seed": seed}
    report = train(
        config,
        manifest,
        data,
        output,
        row_validator=partial(validate_rows, assignment=assignment),
        teacher=TEACHER,
        fingerprint=source_hash,
    )
    print(json.dumps({k: report[k] for k in ("selected_checkpoint", "examples", "wall_seconds")}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["collect-expert", "rollout", "assemble", "train", "eval"])
    parser.add_argument("--pool")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--data", type=Path, default=Path(".local/v05/data"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--arm")
    parser.add_argument("--model", default="qwen3-0.6b")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    study = read(STUDY)
    manifest = load_manifest(ROOT / study["manifest"])
    assignment = load_assignment(ASSIGNMENT, manifest)
    if args.seed is not None and args.seed not in study["training_seeds"]:
        parser.error("Seed not registered")
    if args.pool == "test":
        parser.error("Test evaluation needs a registered protocol and a lock; neither exists yet")
    if args.command == "collect-expert":
        collect_expert(manifest, assignment, args.pool, args.output, args.limit)
    elif args.command == "rollout":
        rollout(manifest, assignment, study, args.seed, args.adapter, args.output, args.limit)
    elif args.command == "assemble":
        assemble(manifest, assignment, args.data, args.seed)
    elif args.command == "train":
        train_arm(manifest, assignment, study, args.data, args.seed, args.output)
    else:
        provider, arm = None, {"name": args.arm, "max_tools": study["decoding"]["max_tools"]}
        if args.arm != "teacher":
            from resolvelab.dialects.policy import DialectPolicy

            arm = model_config(
                study,
                args.model,
                name=args.arm,
                seed=args.seed,
                adapter=str(args.adapter) if args.adapter else None,
            )
            provider = DialectPolicy(arm, args.adapter)
        report = evaluate(
            manifest, assignment, args.pool, arm, args.output, provider, args.resume, args.limit
        )
        print(json.dumps(report["summary"], indent=1))


if __name__ == "__main__":
    main()
