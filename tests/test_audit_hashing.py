"""The audits tolerate a release-version bump and nothing else in the locked source files."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V03 = load("verify_http_study")
V04 = load("verify_casedesk_v2")
V03_LOCK = json.loads((ROOT / "artifacts/v0.3/test-lock.json").read_text(encoding="utf-8"))
V04_LOCK = json.loads((ROOT / "artifacts/v0.4/test-lock.json").read_text(encoding="utf-8"))


def hashes():
    return V03.frozen_source_hash(), V04.locked_source_hash(V04_LOCK["source_files"])


@pytest.fixture
def package(tmp_path, monkeypatch):
    copy = tmp_path / "resolvelab"
    shutil.copytree(ROOT / "src/resolvelab", copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(V03, "PACKAGE", copy)
    monkeypatch.setattr(V04, "PACKAGE", copy)
    return copy


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_current_tree_reproduces_both_locks():
    assert hashes() == (V03_LOCK["source_sha256"], V04_LOCK["source_sha256"])


def test_version_bump_alone_keeps_both_locks(package):
    edit(package / "__init__.py", '__version__ = "0.4.0"', '__version__ = "9.9.9"')
    assert hashes() == (V03_LOCK["source_sha256"], V04_LOCK["source_sha256"])


@pytest.mark.parametrize(
    "path,old,new",
    [
        ("__init__.py", "executable agent workflows", "executable agent workflow"),
        ("httpdesk/grading.py", "def grade(state, claim):", "def grade(state, claim):  # edited"),
    ],
)
def test_any_other_change_breaks_both_locks(package, path, old, new):
    edit(package / path, old, new)
    v03, v04 = hashes()
    assert v03 != V03_LOCK["source_sha256"] and v04 != V04_LOCK["source_sha256"]


def test_v04_only_files_break_only_the_v04_lock(package):
    edit(package / "casedesk/teacher.py", "COMMITTING = {200, 502, 0}", "COMMITTING = {200, 502}")
    v03, v04 = hashes()
    assert v03 == V03_LOCK["source_sha256"] and v04 != V04_LOCK["source_sha256"]


@pytest.mark.parametrize("replacement", ["", '__version__ = "0.4.0"\n__version__ = "0.4.1"'])
def test_version_line_must_appear_exactly_once(package, replacement):
    edit(package / "__init__.py", '__version__ = "0.4.0"', replacement)
    with pytest.raises(AssertionError):
        V03.frozen_source_hash()
    with pytest.raises(AssertionError):
        V04.locked_source_hash(V04_LOCK["source_files"])
