"""Freeze every input of a dialect test run: sources, prompts, schemas, data and adapters.

Unlike the v0.3 and v0.4 locks, the source hash ignores the package's ``__version__`` line
from the start (it is release metadata, not behaviour), so a version bump never needs a
retrofit. Every other byte of every listed file is hashed, with line endings normalised.
"""

import hashlib
import json
import re
from pathlib import Path

from ..benchmark import digest
from ..training import file_hash
from .assignment import dialect_named
from .prompt import initial_messages
from .translate import Translator

PACKAGE = Path(__file__).resolve().parents[1]
VERSION_LINE = re.compile(rb'^__version__ = "[^"\n]*"$', re.MULTILINE)
V04_ARMS = ("bc", "bc-volume", "dagger")
MULTI_ARMS = ("bc-multi", "bc-volume-multi", "dagger-multi")


def source_files(package=PACKAGE):
    paths = [*package.rglob("*.py"), package / "httpdesk" / "demo.json"]
    return sorted(p.relative_to(package).as_posix() for p in paths)


def source_hash(files, package=PACKAGE):
    h = hashlib.sha256()
    for name in sorted(files, key=lambda n: tuple(n.split("/"))):
        data = (package / name).read_bytes().replace(b"\r\n", b"\n")
        if name == "__init__.py":
            data, count = VERSION_LINE.subn(b'__version__ = ""', data)
            if count != 1:
                raise ValueError("__init__.py must contain exactly one __version__ line")
        h.update(name.encode())
        h.update(data)
    return h.hexdigest()


def current_source_hash():
    """The source hash every dialect report, data file and training run records."""
    return source_hash(source_files())


def contract_digests(assignment, pool_ids):
    """Digests of the prompt and grammar every listed episode's dialect presents."""
    names = sorted({assignment["episodes"][spec_id] for spec_id in pool_ids})
    dialects = {name: dialect_named(name) for name in names}
    return {
        "prompts_sha256": digest(
            {n: initial_messages(d, "TASK_PLACEHOLDER") for n, d in dialects.items()}
        ),
        "schemas_sha256": digest({n: Translator(d).schema() for n, d in dialects.items()}),
    }


def selected_adapter(run):
    """The selected checkpoint of a completed training run, with the hashes a lock records."""
    report = json.loads((run / "training.json").read_text(encoding="utf-8"))
    if report["status"] != "completed":
        raise ValueError(f"{run} incomplete")
    checkpoint = report["selected_checkpoint"]
    entry = {
        "checkpoint": checkpoint,
        "sha256": file_hash(run / checkpoint / "adapter_model.safetensors"),
        "training_report_sha256": file_hash(run / "training.json"),
    }
    return entry, {k: report[k] for k in ("data_sha256", "examples", "epochs")}


def build_lock(*, local, manifest, assignment, study, v04_lock, commit, locked_at, seeds):
    """The lock for the test phase. ``local`` holds data/, runs/ and eval/dev of this study."""
    local = Path(local)
    if any((local / "eval/test").glob("*.json")):
        raise ValueError("Test outputs exist; a lock must precede them")
    adapters, training = {}, {}
    for seed in seeds:
        for arm in V04_ARMS:
            # The zero-shot arms are the published v0.4 adapters, pinned by the v0.4 lock.
            adapters[f"{arm}-{seed}"] = dict(v04_lock["adapters"][f"{arm}-{seed}"], source="v0.4 lock")
        for arm in MULTI_ARMS:
            adapters[f"{arm}-{seed}"], training[f"{arm}-{seed}"] = selected_adapter(
                local / "runs" / f"{arm}-{seed}"
            )
    test_ids = [s["id"] for s in manifest["episodes"]["test"]]
    return {
        "phase": "test",
        "locked_at": locked_at,
        "commit": commit,
        "manifest_sha256": digest(manifest),
        "assignment_sha256": digest(assignment),
        "study_sha256": digest(study),
        "v04_lock_sha256": digest(v04_lock),
        "source_files": source_files(),
        "source_sha256": current_source_hash(),
        **contract_digests(assignment, test_ids),
        "data_sha256": {
            p.relative_to(local).as_posix(): file_hash(p)
            for p in sorted((local / "data").rglob("*.jsonl"))
        },
        "dev_report_sha256": {p.name: file_hash(p) for p in sorted((local / "eval/dev").glob("*.json"))},
        "adapters": adapters,
        "training": training,
    }
