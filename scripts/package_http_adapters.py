"""Create local adapter-only archives with checksums; never include base model weights."""

import json
import zipfile
from pathlib import Path

from resolvelab.evaluation import write_report
from resolvelab.training import file_hash

root = Path(__file__).resolve().parents[1]
lock = json.loads((root / "artifacts/v0.3/test-lock.json").read_text(encoding="utf-8"))
destination = root / "dist"
destination.mkdir(exist_ok=True)
items = []
for seed, selected in lock["selected_adapters"].items():
    adapter = root / f".local/http-sft-{seed}" / selected["checkpoint"]
    assert file_hash(adapter / "adapter_model.safetensors") == selected["sha256"]
    path = destination / f"ResolveLab-CaseDesk-Qwen3-0.6B-LoRA-seed-{seed}-v0.3.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(adapter.iterdir()):
            if file.is_file():
                archive.write(file, f"adapter/{file.name}")
        for name in (
            "docs/httpdesk-model-card.md",
            "docs/httpdesk-protocol.md",
            "benchmarks/httpdesk-v1.json",
            "benchmarks/httpdesk-sft-v1.json",
            "artifacts/v0.3/test-lock.json",
            f"artifacts/v0.3/training-{seed}.json",
        ):
            archive.write(root / name, name)
    items.append(
        {
            "seed": int(seed),
            "file": path.name,
            "bytes": path.stat().st_size,
            "archive_sha256": file_hash(path),
            "adapter_sha256": selected["sha256"],
        }
    )
write_report(destination / "http-adapter-checksums.json", {"artifacts": items})
print(json.dumps(items, indent=2))
