"""Verified scripted demonstrations, separated by manifest split before collection."""

import copy
import json
from pathlib import Path

from .benchmark import cases, digest, validate_training_rows
from .evaluation import source_fingerprint, write_report
from .hf_policy import append_observation, initial_messages
from .runner import Runner
from .store import Store, dumps


def collect(manifest, output: Path, data_dir: Path):
    output.mkdir(parents=True, exist_ok=True)
    store = Store(data_dir / "teacher.sqlite")
    runner = Runner(store)
    summary = {
        "manifest_sha256": digest(manifest),
        "source_sha256": source_fingerprint(),
        "teacher": "scripted_runbook_v1",
        "splits": {},
    }
    for split in ("train", "dev"):
        rows, accepted, rejected = [], [], []
        for spec, seed in cases(manifest, split):
            run = runner.execute(store.create(spec.id, seed, spec=spec))
            if not run["verdict"]["passed"]:
                rejected.append({"template": spec.id, "seed": seed, "verdict": run["verdict"]})
                continue
            messages = initial_messages()
            events = [e for e in run["events"] if e["kind"] == "tool"]
            accepted.append({"template": spec.id, "seed": seed, "steps": len(events)})
            for step, event in enumerate(events):
                target = {"name": event["name"], "arguments": event["arguments"]}
                rows.append(
                    {
                        "split": split,
                        "template": spec.id,
                        "seed": seed,
                        "step": step,
                        "manifest_sha256": digest(manifest),
                        "verified_teacher": True,
                        "messages": copy.deepcopy(messages),
                        "target": target,
                    }
                )
                result = {k: v for k, v in event["result"].items() if k != "mutated"}
                # Episode UUIDs are non-semantic; normalize the ticket token for reproducible data.
                if "ticket" in result:
                    result["ticket"] = "ESC-recorded"
                append_observation(messages, event["name"], event["arguments"], result)
        validate_training_rows(rows, manifest, split)
        text = "".join(dumps(row) + "\n" for row in rows)
        (output / f"{split}.jsonl").write_text(text, encoding="utf-8")
        summary["splits"][split] = {
            "episodes": len(accepted),
            "examples": len(rows),
            "accepted": accepted,
            "rejected": rejected,
            "sha256": __import__("hashlib").sha256(text.encode()).hexdigest(),
        }
    write_report(output / "provenance.json", summary)
    return summary


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]
