"""Audits run on hash-checked snapshots of the locked source; src/ may move only outside the core."""

import ast
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from locked_source import (  # noqa: E402
    OUTSIDE_CORE,
    PINNED,
    outside_core_changes,
    read_snapshot,
)
from verify_http_study import V03_SOURCE  # noqa: E402

from resolvelab.dialects.lock import source_hash  # noqa: E402

STUDIES = ("v0.3", "v0.4", "v0.5")


def lock_of(study):
    return json.loads((ROOT / f"artifacts/{study}/test-lock.json").read_text(encoding="utf-8"))


def write_zip(path, snapshot):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in snapshot.items():
            archive.writestr(name, data)


@pytest.fixture
def package(tmp_path):
    """The source as locked at v0.5, standing in for a working tree."""
    copy = tmp_path / "resolvelab"
    with zipfile.ZipFile(ROOT / "artifacts/locked-source/v0.5.zip") as archive:
        archive.extractall(copy)
    return copy


@pytest.mark.parametrize("study", STUDIES)
def test_snapshot_reproduces_its_lock_and_the_working_tree_core_matches_it(study):
    # Both checks raise. What it returns are the edits outside the core, which are allowed.
    outside_core_changes(study, read_snapshot(study))


def test_snapshots_hold_exactly_the_locked_file_lists():
    assert sorted(read_snapshot("v0.3")) == sorted(V03_SOURCE)
    for study in ("v0.4", "v0.5"):
        assert sorted(read_snapshot(study)) == sorted(lock_of(study)["source_files"])


def test_the_package_hash_agrees_with_the_snapshot_check(package):
    lock = lock_of("v0.5")
    assert source_hash(lock["source_files"], package) == lock["source_sha256"]


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s | {"casedesk/world.py": s["casedesk/world.py"] + b"\n# edited\n"},
        lambda s: s | {"providers/ollama.py": s["providers/ollama.py"] + b"\n# edited\n"},
        lambda s: s | {"extra.py": b""},
        lambda s: {name: data for name, data in s.items() if name != "main.py"},
    ],
    ids=["core-file-edited", "outside-file-edited", "file-added", "file-removed"],
)
def test_a_snapshot_that_differs_from_its_lock_is_refused(tmp_path, change):
    (tmp_path / "artifacts/v0.5").mkdir(parents=True)
    (tmp_path / "artifacts/locked-source").mkdir()
    shutil.copy(ROOT / "artifacts/v0.5/test-lock.json", tmp_path / "artifacts/v0.5")
    write_zip(tmp_path / "artifacts/locked-source/v0.5.zip", change(read_snapshot("v0.5")))
    with pytest.raises(AssertionError, match="differs from its lock"):
        read_snapshot("v0.5", tmp_path)


def test_line_endings_and_the_version_are_not_changes(package):
    (package / "casedesk/world.py").write_bytes(
        (package / "casedesk/world.py").read_bytes().replace(b"\n", b"\r\n")
    )
    text = (package / "__init__.py").read_text(encoding="utf-8")
    (package / "__init__.py").write_text(text.replace('"0.4.0"', '"9.9.9"'), encoding="utf-8")
    assert outside_core_changes("v0.5", read_snapshot("v0.5"), package) == []


def test_edits_outside_the_core_are_reported_and_allowed(package):
    with (package / "providers/ollama.py").open("a", encoding="utf-8") as file:
        file.write("# A maintenance edit.\n")
    (package / "main.py").unlink()
    assert outside_core_changes("v0.5", read_snapshot("v0.5"), package) == [
        "main.py",
        "providers/ollama.py",
    ]


@pytest.mark.parametrize("name", ["casedesk/world.py", "dialects/audit.py", "__init__.py"])
def test_an_edit_inside_the_core_is_refused(package, name):
    with (package / name).open("a", encoding="utf-8") as file:
        file.write("# An edit.\n")
    with pytest.raises(AssertionError, match=name):
        outside_core_changes("v0.5", read_snapshot("v0.5"), package)


def test_a_missing_core_file_is_refused(package):
    (package / "httpdesk/service.py").unlink()
    with pytest.raises(AssertionError, match="httpdesk/service.py"):
        outside_core_changes("v0.5", read_snapshot("v0.5"), package)


def imported(source, module):
    """Every ``resolvelab`` module and name a source file imports, at any depth."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = module.split(".")[: 1 - node.level] if node.level > 1 else module.split(".")
                base = ".".join([*parent, base] if base else parent)
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return {name for name in found if name.split(".")[0] == "resolvelab"}


def reached_by(scripts, snapshot):
    """The locked files these scripts import, directly or through locked files."""
    reached = {}
    stack = [name for path in scripts for name in imported(path.read_text(encoding="utf-8"), "")]
    while stack:
        parts = stack.pop().split(".")
        for end in range(1, len(parts) + 1):
            path = "/".join(parts[1:end])
            package = f"{path}/__init__.py".removeprefix("/")
            name = package if package in snapshot else f"{path}.py"
            if name in snapshot and name not in reached:
                reached[name] = True
                # A package's relative imports start at itself, a module's at its package.
                anchor = ".".join(parts[: end if name == package else end - 1])
                stack.extend(imported(snapshot[name].decode(), anchor))
    return set(reached)


def test_no_script_reaches_a_file_outside_the_core():
    snapshot = read_snapshot("v0.5")
    assert OUTSIDE_CORE <= set(snapshot)
    reached = reached_by(sorted((ROOT / "scripts").glob("*.py")), snapshot)
    # The walk does see the study code, through relative imports too.
    assert {"casedesk/world.py", "dialects/runner.py", "httpdesk/service.py", "hf_policy.py"} <= reached
    assert reached.isdisjoint(OUTSIDE_CORE)


def test_the_walk_catches_a_script_that_reaches_outside_the_core(tmp_path):
    script = tmp_path / "script.py"
    script.write_text("from resolvelab.casedesk.cli import main\n", encoding="utf-8")
    assert "casedesk/cli.py" in reached_by([script], read_snapshot("v0.5"))


def test_the_rerun_imports_only_the_snapshot_and_keeps_the_exit_status(tmp_path):
    script = tmp_path / "audit.py"
    script.write_text(
        """
import sys
from locked_source import run_on_locked_source
run_on_locked_source("v0.4")
import resolvelab
print(resolvelab.__file__)
print(resolvelab.__version__)
try:
    import resolvelab.dialects
except ModuleNotFoundError:
    print("no dialects")
sys.exit(7)
""",
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k != PINNED}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "scripts"), str(ROOT / "src")])
    result = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True)
    assert result.returncode == 7, result.stderr
    file, version, missing = result.stdout.splitlines()[-3:]
    assert not Path(file).resolve().is_relative_to(ROOT)
    assert (version, missing) == ("0.3.0", "no dialects")
