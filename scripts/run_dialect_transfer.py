"""Run the dialect transfer study as a resumable job graph (each step its own process).

Phase ``dev`` builds the dialect data, trains every registered seed (bc-multi -> DAgger
rollout -> matched bc-volume-multi and dagger-multi) and evaluates every arm on dev, each
episode in its train-split dialect. Phase ``test`` refuses to start without
artifacts/v0.5/test-lock.json and checks every adapter against it; it evaluates every arm in
held-out dialects, then the multi arms on the study contract (``bc-volume-multi`` last, the
first measurement the protocol drops if compute runs over). Steps whose outputs exist are
skipped, so a crash or reboot resumes where it stopped.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local/v05"
DATA = LOCAL / "data"
RUNS = LOCAL / "runs"
LOCK = ROOT / "artifacts/v0.5/test-lock.json"
V04_LOCK = ROOT / "artifacts/v0.4/test-lock.json"
CLI = [sys.executable, "scripts/dialect_transfer.py"]
V04_ARMS = ("bc", "bc-volume", "dagger")
MULTI_ARMS = ("bc-multi", "bc-volume-multi", "dagger-multi")
STUDY_CONTRACT_ORDER = ("bc-multi", "dagger-multi", "bc-volume-multi")
# Peak MiB per job kind on the 8 GB card (the v0.4 figures). A GPU job starts only when this
# much is free, and never sooner than SETTLE seconds after the last start, so processes that
# do not belong to this graph are respected.
GPU_MIB = {"train": 3000, "rollout": 2400, "eval-0.6b": 2400, "eval-1.7b": 5200}
SETTLE = 90


def gpu_need(job):
    kind = job.command[0]
    if kind == "eval":
        return GPU_MIB["eval-1.7b" if "qwen3-1.7b" in map(str, job.command) else "eval-0.6b"]
    return GPU_MIB.get(kind, 0)


def free_mib():
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(out.stdout.split()[0])


def selected(run):
    report = json.loads((Path(run) / "training.json").read_text(encoding="utf-8"))
    if report.get("status") != "completed":
        raise RuntimeError(f"{run} did not complete")
    return Path(run) / report["selected_checkpoint"]


class Job:
    def __init__(self, name, output, command, deps=(), gpu=True):
        self.name, self.output, self.command, self.deps, self.gpu = (
            name,
            Path(output),
            command,
            deps,
            gpu,
        )


def adapter_arms(study, v04_runs):
    """(arm, seed, adapter, training job): the published v0.4 adapters, then the new ones."""
    v04 = json.loads(V04_LOCK.read_text(encoding="utf-8"))["adapters"]
    for seed in study["training_seeds"]:
        for arm in V04_ARMS:
            checkpoint = v04[f"{arm}-{seed}"]["checkpoint"]
            yield arm, seed, str(Path(v04_runs) / f"{arm}-{seed}" / checkpoint), None
    for arm in MULTI_ARMS:
        for seed in study["training_seeds"]:
            yield arm, seed, f"SELECTED:{RUNS / f'{arm}-{seed}'}", f"train-{arm}-{seed}"


def training_jobs(study):
    jobs = []
    for pool in ("train_core", "train_pool", "dev"):
        out = DATA / f"expert-{pool}.jsonl"
        jobs.append(
            Job(f"expert-{pool}", out, ["collect-expert", "--pool", pool, "--output", out], gpu=False)
        )
    experts = tuple(f"expert-{p}" for p in ("train_core", "train_pool", "dev"))
    jobs.append(
        Job(
            "assemble-bc-multi",
            DATA / "bc-multi/train.jsonl",
            ["assemble", "--data", DATA],
            experts,
            gpu=False,
        )
    )
    for seed in study["training_seeds"]:
        s = str(seed)
        jobs.append(
            Job(
                f"train-bc-multi-{s}",
                RUNS / f"bc-multi-{s}/training.json",
                ["train", "--seed", s, "--data", DATA / "bc-multi", "--output", RUNS / f"bc-multi-{s}"],
                ("assemble-bc-multi",),
            )
        )
        jobs.append(
            Job(
                f"rollout-{s}",
                DATA / f"dagger-{s}.jsonl",
                [
                    "rollout",
                    "--seed",
                    s,
                    "--adapter",
                    f"SELECTED:{RUNS / f'bc-multi-{s}'}",
                    "--output",
                    DATA / f"dagger-{s}.jsonl",
                ],
                (f"train-bc-multi-{s}",),
            )
        )
        jobs.append(
            Job(
                f"assemble-{s}",
                DATA / f"dagger-multi-{s}/train.jsonl",
                ["assemble", "--seed", s, "--data", DATA],
                (f"rollout-{s}",),
                gpu=False,
            )
        )
        for arm in ("bc-volume-multi", "dagger-multi"):
            jobs.append(
                Job(
                    f"train-{arm}-{s}",
                    RUNS / f"{arm}-{s}/training.json",
                    [
                        "train",
                        "--seed",
                        s,
                        "--data",
                        DATA / f"{arm}-{s}",
                        "--output",
                        RUNS / f"{arm}-{s}",
                    ],
                    (f"assemble-{s}",),
                )
            )
    return jobs


def eval_job(name, path, pool, arm, extra, deps=(), contract="assigned"):
    command = ["eval", "--pool", pool, "--arm", arm, *extra, "--output", path]
    if contract != "assigned":
        command[1:1] = ["--contract", contract]
    return Job(name, path, command, deps)


def eval_jobs(study, pool, v04_runs):
    out = LOCAL / "eval" / pool
    jobs = [
        eval_job(
            f"{pool}-base-1.7b",
            out / "base-1.7b.json",
            pool,
            "base-1.7b",
            ["--model", "qwen3-1.7b"],
        )
    ]
    arms = list(adapter_arms(study, v04_runs))
    for arm, seed, adapter, training in arms:
        jobs.append(
            eval_job(
                f"{pool}-{arm}-{seed}",
                out / f"{arm}-{seed}.json",
                pool,
                arm,
                ["--seed", str(seed), "--adapter", adapter],
                (training,) if training and pool == "dev" else (),
            )
        )
    if pool == "test":
        # The study-contract runs wait for every registered held-out evaluation, and
        # bc-volume-multi goes last: it is the first measurement dropped if compute runs over.
        held_out = tuple(j.name for j in jobs)
        order = {arm: i for i, arm in enumerate(STUDY_CONTRACT_ORDER)}
        for arm, seed, adapter, training in sorted((a for a in arms if a[3]), key=lambda a: order[a[0]]):
            jobs.append(
                eval_job(
                    f"test-study-{arm}-{seed}",
                    LOCAL / "eval/study-contract" / f"{arm}-{seed}.json",
                    pool,
                    arm,
                    ["--seed", str(seed), "--adapter", adapter],
                    held_out,
                    contract="study",
                )
            )
    return jobs


def complete(job):
    """Reports must say ``completed``; a running/errored report or training log is not done."""
    if not job.output.exists():
        return False
    if job.output.suffix == ".json":
        return json.loads(job.output.read_text(encoding="utf-8")).get("status") == "completed"
    return True


def command(job):
    parts = []
    for part in job.command:
        part = str(part)
        parts.append(
            str(selected(part.removeprefix("SELECTED:"))) if part.startswith("SELECTED:") else part
        )
    if parts[0] == "eval" and job.output.exists():
        parts.append("--resume")
    if parts[0] == "train" and job.output.exists():
        raise SystemExit(f"{job.output.parent} holds an incomplete run; inspect and move it aside")
    return CLI + parts


def check_lock(jobs):
    from resolvelab.dialects.lock import current_source_hash
    from resolvelab.training import file_hash

    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if current_source_hash() != lock["source_sha256"]:
        raise SystemExit("Source differs from the test lock")
    for job in jobs:
        parts = command(job)
        if "--adapter" in parts:
            key = f"{parts[parts.index('--arm') + 1]}-{parts[parts.index('--seed') + 1]}"
            adapter = Path(parts[parts.index("--adapter") + 1]) / "adapter_model.safetensors"
            if lock["adapters"].get(key, {}).get("sha256") != file_hash(adapter):
                raise SystemExit(f"{key}: adapter does not match the test lock")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["dev", "test"])
    parser.add_argument("--v04-runs", type=Path, default=ROOT / ".local/v04/runs")
    parser.add_argument("--parallel", type=int, default=2, help="concurrent GPU jobs")
    parser.add_argument("--only", nargs="*", help="job-name prefixes")
    args = parser.parse_args()
    study = json.loads((ROOT / "benchmarks/casedesk-v2-study.json").read_text(encoding="utf-8"))
    jobs = training_jobs(study) if args.phase == "dev" else []
    jobs += eval_jobs(study, args.phase, args.v04_runs)
    if args.only:
        jobs = [j for j in jobs if any(j.name.startswith(o) for o in args.only)]
    if args.phase == "test":
        if not LOCK.exists():
            raise SystemExit("Test evaluation requires artifacts/v0.5/test-lock.json")
        check_lock(jobs)
    names = {j.name for j in jobs}
    done = {j.name for j in jobs if complete(j)}
    running, failed = {}, set()
    last_gpu_start = -SETTLE
    (LOCAL / "logs").mkdir(parents=True, exist_ok=True)
    while True:
        for name, (job, process, log) in list(running.items()):
            if process.poll() is None:
                continue
            log.close()
            del running[name]
            ok = process.returncode == 0 and complete(job)
            (done if ok else failed).add(name)
            print(time.strftime("%H:%M:%S"), name, "ok" if ok else "FAILED", flush=True)
        waiting = [j for j in jobs if j.name not in done | failed | set(running)]
        for job in waiting:
            if any(d in failed for d in job.deps):
                failed.add(job.name)
        ready = [
            j
            for j in waiting
            if j.name not in failed and all(d in done or d not in names for d in j.deps)
        ]
        busy = sum(job.gpu for job, _, _ in running.values())
        for job in ready:
            if job.gpu:
                if busy >= args.parallel or time.monotonic() - last_gpu_start < SETTLE:
                    continue
                if free_mib() < gpu_need(job) + 300:
                    continue
                last_gpu_start = time.monotonic()
            log = open(LOCAL / "logs" / f"{job.name}.log", "a", encoding="utf-8")
            print(time.strftime("%H:%M:%S"), "start", job.name, flush=True)
            process = subprocess.Popen(command(job), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            running[job.name] = (job, process, log)
            busy += job.gpu
        if not running and not ready:
            break
        time.sleep(5)
    print("done:", len(done & names), "of", len(names), "failed:", sorted(failed), flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
