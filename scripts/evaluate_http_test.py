"""Execute the locked test once for each registered arm; no selection or tuning."""

import json
import subprocess
import sys
from pathlib import Path

from resolvelab.benchmark import digest
from resolvelab.httpdesk.benchmark import source_hash
from resolvelab.httpdesk.schema import action_schema, initial_messages
from resolvelab.training import file_hash

lock = json.loads(Path("artifacts/v0.3/test-lock.json").read_text(encoding="utf-8"))
assert lock["source_sha256"] == source_hash(), "Core code changed after test lock"
assert lock["prompt_sha256"] == digest(initial_messages("TASK_PLACEHOLDER"))
assert lock["schema_sha256"] == digest(action_schema())
commands = [
    ["--output", ".local/http-base-test.json"],
    ["--larger", "--output", ".local/http-large-test.json"],
]
for seed, item in lock["selected_adapters"].items():
    adapter = Path(f".local/http-sft-{seed}") / item["checkpoint"]
    assert file_hash(adapter / "adapter_model.safetensors") == item["sha256"]
    commands.append(
        ["--seed", seed, "--adapter", str(adapter), "--output", f".local/http-sft-{seed}-test.json"]
    )
for command in commands:
    subprocess.run(
        [sys.executable, "scripts/http_experiment.py", "eval", "--split", "test", *command], check=True
    )
