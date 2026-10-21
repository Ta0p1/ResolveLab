"""Run the three registered seeds serially, freeing GPU memory between processes."""

import json
import subprocess
import sys
from pathlib import Path

config = json.loads(Path("benchmarks/httpdesk-sft-v1.json").read_text(encoding="utf-8"))
for seed in config["training_seeds"]:
    output = Path(f".local/http-sft-{seed}")
    subprocess.run(
        [
            sys.executable,
            "scripts/http_experiment.py",
            "train",
            "--seed",
            str(seed),
            "--data",
            ".local/http-data-ordered",
            "--output",
            str(output),
        ],
        check=True,
    )
    report = json.loads((output / "training.json").read_text(encoding="utf-8"))
    subprocess.run(
        [
            sys.executable,
            "scripts/http_experiment.py",
            "eval",
            "--seed",
            str(seed),
            "--adapter",
            str(output / report["selected_checkpoint"]),
            "--split",
            "dev",
            "--output",
            f".local/http-sft-{seed}-dev.json",
        ],
        check=True,
    )
