"""Run the CaseDesk v2 study as a resumable job graph (each step its own process).

Phase ``dev`` builds data, trains every registered seed (bc -> DAgger rollout -> matched
bc-volume and dagger) and evaluates all arms on dev. Phase ``test`` refuses to start without
artifacts/v0.4/test-lock.json and checks every adapter against it. Steps whose outputs exist
are skipped, so a crash or reboot resumes where it stopped.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local/v04"
DATA = LOCAL / "data"
RUNS = LOCAL / "runs"
LOCK = ROOT / "artifacts/v0.4/test-lock.json"
CLI = [sys.executable, "scripts/casedesk_v2.py"]
TRAINED = ("bc", "bc-volume", "dagger")
# Peak MiB per job kind on the 8 GB card (measured on the v0.3 runs plus margin). A GPU job
# starts only when this much is free, and never sooner than SETTLE seconds after the last
# start, so processes that do not belong to this graph are respected.
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


def adapter_arms(study, v03_root):
    lock = json.loads((ROOT / "artifacts/v0.3/test-lock.json").read_text(encoding="utf-8"))
    for seed in study["training_seeds"]:
        checkpoint = lock["selected_adapters"][str(seed)]["checkpoint"]
        yield "v03-lora", seed, str(Path(v03_root) / f"http-sft-{seed}" / checkpoint), ()
        for arm in TRAINED:
            yield arm, seed, f"SELECTED:{RUNS / f'{arm}-{seed}'}", (f"train-{arm}-{seed}",)


def training_jobs(study):
    jobs = []
    for pool in ("train_core", "train_pool", "dev"):
        out = DATA / f"expert-{pool}.jsonl"
        jobs.append(
            Job(f"expert-{pool}", out, ["collect-expert", "--pool", pool, "--output", out], gpu=False)
        )
    experts = tuple(f"expert-{p}" for p in ("train_core", "train_pool", "dev"))
    jobs.append(
        Job("assemble-bc", DATA / "bc/train.jsonl", ["assemble", "--data", DATA], experts, gpu=False)
    )
    for seed in study["training_seeds"]:
        s = str(seed)
        jobs.append(
            Job(
                f"train-bc-{s}",
                RUNS / f"bc-{s}/training.json",
                ["train", "--seed", s, "--data", DATA / "bc", "--output", RUNS / f"bc-{s}"],
                ("assemble-bc",),
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
                    f"SELECTED:{RUNS / f'bc-{s}'}",
                    "--output",
                    DATA / f"dagger-{s}.jsonl",
                ],
                (f"train-bc-{s}",),
            )
        )
        jobs.append(
            Job(
                f"assemble-{s}",
                DATA / f"dagger-{s}/train.jsonl",
                ["assemble", "--seed", s, "--data", DATA],
                (f"rollout-{s}",),
                gpu=False,
            )
        )
        for arm in ("bc-volume", "dagger"):
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


def eval_jobs(study, pool, v03_root, thinking, three_demo=False):
    out = LOCAL / "eval" / pool
    jobs = [
        Job(
            f"{pool}-base-0.6b",
            out / "base-0.6b.json",
            ["eval", "--pool", pool, "--arm", "base-0.6b", "--output", out / "base-0.6b.json"],
        ),
        Job(
            f"{pool}-base-1.7b",
            out / "base-1.7b.json",
            [
                "eval",
                "--pool",
                pool,
                "--arm",
                "base-1.7b",
                "--model",
                "qwen3-1.7b",
                "--output",
                out / "base-1.7b.json",
            ],
        ),
    ]
    if thinking:
        name = f"think{thinking}-1.7b"
        jobs.append(
            Job(
                f"{pool}-{name}",
                out / f"{name}.json",
                [
                    "eval",
                    "--pool",
                    pool,
                    "--arm",
                    name,
                    "--model",
                    "qwen3-1.7b",
                    "--thinking",
                    str(thinking),
                    "--output",
                    out / f"{name}.json",
                ],
            )
        )
    if three_demo:
        for model in ("0.6b", "1.7b"):
            name = f"base-{model}-3demo"
            jobs.append(
                Job(
                    f"{pool}-{name}",
                    out / f"{name}.json",
                    ["eval", "--pool", pool, "--arm", name, "--model", f"qwen3-{model}", "--three-demo"]
                    + ["--output", out / f"{name}.json"],
                )
            )
    for arm, seed, adapter, deps in adapter_arms(study, v03_root):
        path = out / f"{arm}-{seed}.json"
        jobs.append(
            Job(
                f"{pool}-{arm}-{seed}",
                path,
                [
                    "eval",
                    "--pool",
                    pool,
                    "--arm",
                    arm,
                    "--seed",
                    str(seed),
                    "--adapter",
                    adapter,
                    "--output",
                    path,
                ],
                deps if pool == "dev" else (),
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
    from resolvelab.training import file_hash

    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for job in jobs:
        parts = command(job)
        if "--adapter" in parts:
            key = job.name.removeprefix("test-")
            adapter = Path(parts[parts.index("--adapter") + 1]) / "adapter_model.safetensors"
            if lock["adapters"].get(key, {}).get("sha256") != file_hash(adapter):
                raise SystemExit(f"{key}: adapter does not match the test lock")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["dev", "test"])
    parser.add_argument("--v03-adapters", type=Path, required=True)
    parser.add_argument("--parallel", type=int, default=2, help="concurrent GPU jobs")
    parser.add_argument("--thinking", type=int, default=0, help="add a thinking-mode 1.7B arm")
    parser.add_argument("--three-demo", action="store_true", help="add three-demo base arms")
    parser.add_argument("--only", nargs="*", help="job-name prefixes")
    args = parser.parse_args()
    study = json.loads((ROOT / "benchmarks/casedesk-v2-study.json").read_text(encoding="utf-8"))
    jobs = training_jobs(study) if args.phase == "dev" else []
    jobs += eval_jobs(study, args.phase, args.v03_adapters, args.thinking, args.three_demo)
    if args.only:
        jobs = [j for j in jobs if any(j.name.startswith(o) for o in args.only)]
    if args.phase == "test":
        if not LOCK.exists():
            raise SystemExit("Test evaluation requires artifacts/v0.4/test-lock.json")
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
