"""Benchmark files resolve in a checkout and in a wheel; CI runs the built wheel for real."""

from pathlib import Path

from resolvelab import packaged
from resolvelab.casedesk.cli import MANIFEST
from resolvelab.casedesk.env import CaseDeskEnv
from resolvelab.providers import STUDY

ROOT = Path(__file__).resolve().parents[1]


def test_a_checkout_reads_the_repository_files():
    assert MANIFEST == ROOT / "benchmarks/casedesk-v2.json"
    assert STUDY == ROOT / "benchmarks/casedesk-v2-study.json"
    assert CaseDeskEnv().specs


def test_a_wheel_reads_its_packaged_files(tmp_path, monkeypatch):
    (tmp_path / "benchmarks").mkdir()
    (tmp_path / "benchmarks/casedesk-v2.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(packaged, "PACKAGE", tmp_path)
    assert packaged.benchmark_file("casedesk-v2.json") == tmp_path / "benchmarks/casedesk-v2.json"
