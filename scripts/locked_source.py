"""Run an audit on the exact source its study locked, whatever ``src/`` holds today.

An audit replays published evidence on the code that produced it. Those bytes live in
``artifacts/locked-source/<study>.zip``: they must reproduce the lock's source hash, and the audit
re-runs itself in a process that can import nothing else from the package. ``src/`` is then held to
a narrower rule: it must match the snapshot, except in ``OUTSIDE_CORE``.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import resolvelab

ROOT = Path(__file__).resolve().parents[1]
WORKING_TREE = ROOT / "src/resolvelab"
PINNED = "RESOLVELAB_LOCKED_SOURCE"
VERSION_LINE = re.compile(rb'^__version__ = "[^"\n]*"$', re.MULTILINE)
# What each lock's hash wrote in place of the release version, which is metadata, not behaviour.
LOCKED_VERSION_LINES = {
    "v0.3": b'__version__ = "0.3.0"',
    "v0.4": b'__version__ = "0.3.0"',
    "v0.5": b'__version__ = ""',
}
# Locked only because the locks hash the whole package. No script imports them, directly or through
# the study code (tests/test_locked_source.py walks the imports), so they can be maintained.
OUTSIDE_CORE = frozenset(
    """
    __main__.py api.py cli.py main.py casedesk/cli.py casedesk/env.py providers/__init__.py
    providers/anthropic.py providers/base.py providers/ollama.py providers/openai_compat.py
    """.split()
)


def normalised(name, data, version_line):
    data = data.replace(b"\r\n", b"\n")
    if name == "__init__.py":
        data, count = VERSION_LINE.subn(version_line, data)
        assert count == 1, "__init__.py must contain exactly one __version__ line"
    return data


def source_digest(snapshot, version_line):
    """The locks' source hash. It covers file names, so a file added or removed changes it too."""
    h = hashlib.sha256()
    for name in sorted(snapshot, key=lambda n: tuple(n.split("/"))):
        h.update(name.encode())
        h.update(normalised(name, snapshot[name], version_line))
    return h.hexdigest()


def read_snapshot(study, root=ROOT):
    """The study's locked files as ``{name: bytes}``, refused unless they reproduce its lock."""
    lock = json.loads((root / f"artifacts/{study}/test-lock.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(root / f"artifacts/locked-source/{study}.zip") as archive:
        snapshot = {name: archive.read(name) for name in archive.namelist()}
    digest = source_digest(snapshot, LOCKED_VERSION_LINES[study])
    assert digest == lock["source_sha256"], f"{study} source snapshot differs from its lock"
    return snapshot


def outside_core_changes(study, snapshot, package=WORKING_TREE):
    """Refuse a working tree that differs from the snapshot in the core; list its other changes."""
    line = LOCKED_VERSION_LINES[study]
    changed = sorted(
        name
        for name, data in snapshot.items()
        if not (package / name).is_file()
        or normalised(name, (package / name).read_bytes(), line) != normalised(name, data, line)
    )
    core = [name for name in changed if name not in OUTSIDE_CORE]
    assert not core, f"Locked source of the {study} study core changed: {', '.join(core)}"
    return changed


def run_on_locked_source(study):
    """Re-run this audit on the snapshot and exit with its status; returns only in that re-run.

    The hash is checked here, by code outside the snapshot, so a snapshot cannot vouch for itself.
    """
    pinned = os.environ.get(PINNED)
    if pinned:
        running = Path(resolvelab.__file__).resolve().parent
        assert running == Path(pinned).resolve(), f"{study} audit is not running on its snapshot"
        return
    snapshot = read_snapshot(study)
    changed = outside_core_changes(study, snapshot)
    if changed:
        print(
            f"{study}: src/ differs from the lock outside the study core: {', '.join(changed)}",
            flush=True,
        )
    with tempfile.TemporaryDirectory() as directory:
        package = Path(directory) / "src/resolvelab"
        for name, data in snapshot.items():
            (package / name).parent.mkdir(parents=True, exist_ok=True)
            (package / name).write_bytes(data)
        # casedesk.manifest reads the v0.3 manifest beside src/, as it does in a checkout.
        shutil.copytree(ROOT / "benchmarks", Path(directory) / "benchmarks")
        path = [str(package.parent), os.environ.get("PYTHONPATH", "")]
        env = os.environ | {PINNED: str(package), "PYTHONPATH": os.pathsep.join(filter(None, path))}
        status = subprocess.run([sys.executable, *sys.argv], env=env).returncode
    sys.exit(status)
