"""Write an immutable pre-training or pre-test study lock; commit it before the phase."""

import argparse
import json
from pathlib import Path

from resolvelab.benchmark import digest
from resolvelab.evaluation import write_report
from resolvelab.httpdesk.benchmark import load_manifest, source_hash, validate_rows
from resolvelab.httpdesk.schema import action_schema, initial_messages
from resolvelab.store import utcnow
from resolvelab.training import file_hash

parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=["training", "test"])
args = parser.parse_args()
destination = Path(f"artifacts/v0.3/{args.phase}-lock.json")
if destination.exists():
    raise ValueError("Lock already exists")
manifest = load_manifest("benchmarks/httpdesk-v1.json")
config = json.loads(Path("benchmarks/httpdesk-sft-v1.json").read_text(encoding="utf-8"))
data = Path(".local/http-data-ordered")
for split in ("train", "dev"):
    validate_rows(
        [
            json.loads(line)
            for line in (data / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
        ],
        manifest,
        split,
    )
report = {
    "phase": args.phase,
    "locked_at": utcnow(),
    "source_sha256": source_hash(),
    "manifest_sha256": digest(manifest),
    "config_sha256": digest(config),
    "prompt_sha256": digest(initial_messages("TASK_PLACEHOLDER")),
    "schema_sha256": digest(action_schema()),
    "data_sha256": {s: file_hash(data / f"{s}.jsonl") for s in ("train", "dev")},
    "training_seeds": config["training_seeds"],
    "holdout_registration_commit": "7e5ffb4",
}
if args.phase == "test":
    control_config = json.loads(
        Path("benchmarks/httpdesk-ollama-control.json").read_text(encoding="utf-8")
    )
    report["ollama_control_config_sha256"] = digest(control_config)
    report["ollama_control_script_sha256"] = file_hash("scripts/http_ollama_control.py")
    training_lock = json.loads(Path("artifacts/v0.3/training-lock.json").read_text(encoding="utf-8"))
    for key in (
        "source_sha256",
        "manifest_sha256",
        "config_sha256",
        "prompt_sha256",
        "schema_sha256",
        "data_sha256",
    ):
        if report[key] != training_lock[key]:
            raise ValueError(f"Study changed after training lock: {key}")
    report["selected_adapters"] = {}
    for seed in config["training_seeds"]:
        folder = Path(f".local/http-sft-{seed}")
        training = json.loads((folder / "training.json").read_text(encoding="utf-8"))
        if training["status"] != "completed":
            raise ValueError("Incomplete training")
        selected = min(training["epochs"], key=lambda x: x["dev_loss"])
        if training["selected_checkpoint"] != selected["checkpoint"]:
            raise ValueError("Wrong checkpoint selection")
        weight_hash = file_hash(folder / selected["checkpoint"] / "adapter_model.safetensors")
        if weight_hash != selected["adapter_sha256"]:
            raise ValueError("Changed weights")
        report["selected_adapters"][str(seed)] = {
            "checkpoint": selected["checkpoint"],
            "sha256": weight_hash,
            "training_report_sha256": file_hash(folder / "training.json"),
        }
write_report(destination, report)
print(json.dumps(report, indent=2))
