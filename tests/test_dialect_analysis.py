"""The registered dialect-transfer analysis on synthetic reports: every decision rule's branch."""

import json
import random
from pathlib import Path

import pytest

from resolvelab.casedesk.evaluate import summarize
from resolvelab.casedesk.manifest import load_manifest
from resolvelab.dialects.analysis import analyze, markdown, paired_seed_bootstrap, transfer
from resolvelab.dialects.assignment import load_assignment

ROOT = Path(__file__).resolve().parents[1]
SEEDS = (3407, 42, 2026)
DRAWS = 300


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(ROOT / "benchmarks/casedesk-v2.json")


@pytest.fixture(scope="module")
def assignment(manifest):
    return load_assignment(ROOT / "benchmarks/casedesk-dialects-v1.json", manifest)


def outcomes(name, seed, rate, count=120):
    rng = random.Random(f"{name}:{seed}:{rate}")
    return [rng.random() < rate for _ in range(count)]


def write(directory, manifest, name, rate, seeds=SEEDS, pool="test"):
    directory.mkdir(parents=True, exist_ok=True)
    for seed in seeds:
        rows = []
        for spec, ok in zip(manifest["episodes"][pool], outcomes(name, seed, rate)):
            rows.append(
                {
                    "spec_id": spec["id"],
                    "composition": spec["composition"],
                    "passed": ok,
                    "claim": "resolved" if ok else None,
                    "failure_category": None if ok else "unfinished",
                    "unsafe_mutations": 0,
                    "redundant_commits": 0,
                    "false_success": False,
                    "spurious_escalation": False,
                    "v03_passed": ok,
                    "located_target": True,
                    "decisions": 6,
                    "schema_valid": 6,
                    "tools": 6,
                    "output_tokens": 0,
                    "thinking_tokens": 0,
                    "input_tokens": 0,
                    "seconds": 1.0,
                }
            )
        report = {"status": "completed", "pool": pool, "arm": {"name": name, "seed": seed}, "rows": rows}
        report["summary"] = summarize(rows)
        stem = name if seed is None else f"{name}-{seed}"
        (directory / f"{stem}.json").write_text(json.dumps(report), encoding="utf-8")


def test_paired_seed_bootstrap_is_exact_at_the_extremes():
    zeros, ones = [[0] * 12] * 3, [[1] * 12] * 3
    strata = ["a"] * 6 + ["b"] * 6
    assert paired_seed_bootstrap(zeros, zeros, strata, draws=50) == {"estimate": 0.0, "ci95": [0.0, 0.0]}
    assert paired_seed_bootstrap(zeros, ones, strata, draws=50) == {"estimate": 1.0, "ci95": [1.0, 1.0]}
    with pytest.raises(ValueError):
        paired_seed_bootstrap(zeros, ones[:2], strata)


def test_every_registered_branch(manifest, assignment, tmp_path):
    study, dialect, multi = tmp_path / "study", tmp_path / "dialect", tmp_path / "multi"
    for name in ("bc", "bc-volume", "dagger"):
        write(study, manifest, name, 0.95)
    write(study, manifest, "base-1.7b", 0.25, seeds=(None,))
    write(dialect, manifest, "bc", 0.4)  # does not transfer
    write(dialect, manifest, "bc-volume", 0.75)  # partial
    write(dialect, manifest, "dagger", 0.95)  # same outcomes as on the study contract: transfers
    write(dialect, manifest, "base-1.7b", 0.2, seeds=(None,))
    write(dialect, manifest, "bc-multi", 0.8)  # Q2 supported
    write(dialect, manifest, "bc-volume-multi", 0.97)
    write(dialect, manifest, "dagger-multi", 0.98)  # Q3 at the ceiling
    write(multi, manifest, "bc-multi", 0.85)  # more than 5 pp below v0.4 bc on the study contract
    write(multi, manifest, "dagger-multi", 0.94)
    report = analyze(dialect, study, manifest, assignment, multi, draws=DRAWS)
    assert {k: v["classification"] for k, v in report["transfer"].items()} == {
        "bc": "does not transfer",
        "bc-volume": "partial",
        "dagger": "transfers",
        "base-1.7b": "does not transfer",
    }
    assert report["transfer"]["dagger"]["dialect_minus_study"]["estimate"] == 0.0
    assert report["decisions"] == {"Q2": "supported", "Q3": "uninformative (ceiling)"}
    assert report["cost_of_diversity"]["bc-multi"]["stated_as_cost"]
    assert not report["cost_of_diversity"]["dagger-multi"]["stated_as_cost"]
    assert report["baseline_is_headline"] is False
    assert {"token_revision", "cursor_opaque", "unit_milliseconds", "conflict_is_409"} <= set(
        report["arms"]["bc-multi"]["slices"]
    )
    text = markdown(report)
    assert "Q2 (registered rule): **supported**" in text
    dagger = next(
        line for line in text.splitlines() if line.startswith("| dagger |") and "transfer" in line
    )
    assert "| 0.0 |" in dagger and dagger.endswith("| transfers |")


def test_harmful_and_inconclusive_and_a_baseline_headline(manifest, assignment, tmp_path):
    study, dialect = tmp_path / "study", tmp_path / "dialect"
    write(study, manifest, "bc", 0.9)
    write(dialect, manifest, "bc", 0.7)
    write(dialect, manifest, "bc-multi", 0.2)
    write(dialect, manifest, "bc-volume-multi", 0.5)
    write(dialect, manifest, "dagger-multi", 0.52)
    write(dialect, manifest, "base-1.7b", 0.8, seeds=(None,))
    report = analyze(dialect, study, manifest, assignment, draws=DRAWS)
    assert report["decisions"] == {"Q2": "harmful", "Q3": "inconclusive at this size"}
    assert report["baseline_is_headline"] is True
    assert "that is the headline" in markdown(report)


def test_q1_refuses_unpaired_seeds(manifest, tmp_path):
    from resolvelab.casedesk.analysis import load_arms

    write(tmp_path / "a", manifest, "bc", 0.9)
    write(tmp_path / "b", manifest, "bc", 0.9, seeds=(42,))
    a, _ = load_arms(tmp_path / "a", manifest, "test")
    b, _ = load_arms(tmp_path / "b", manifest, "test")
    with pytest.raises(ValueError, match="same seeds"):
        transfer(a["bc"], b["bc"], [s["composition"] for s in manifest["episodes"]["test"]])


def test_analysis_reads_the_published_v04_reports(manifest, assignment):
    """With the published v0.4 test reports as both conditions, every shift is exactly zero."""
    published = ROOT / "artifacts/v0.4/test"
    report = analyze(published, published, manifest, assignment, draws=50)
    shifts = {k: v["dialect_minus_study"] for k, v in report["transfer"].items()}
    assert set(shifts) == {"bc", "bc-volume", "dagger", "base-1.7b"}
    assert all(s == {"estimate": 0.0, "ci95": [0.0, 0.0]} for s in shifts.values())
    assert report["transfer"]["dagger"]["classification"] == "transfers"
    assert report["transfer"]["base-1.7b"]["classification"] == "does not transfer"
    assert round(report["arms"]["dagger"]["success"]["mean"], 3) == 0.983
