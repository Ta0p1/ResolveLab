"""The registered v2 analysis: coverage checks, paired comparisons and the decision rule."""

import json

import pytest

from resolvelab.casedesk.analysis import analyze, decide, load_arms

SPECS = [
    {"id": f"e{i}", "composition": f"c{i % 2}", "target_pos": i % 3, "phrasing_group": "seen"}
    for i in range(8)
]
MANIFEST = {"episodes": {"test": SPECS}}


def row(spec, passed, **extra):
    return {
        "spec_id": spec["id"],
        "composition": spec["composition"],
        "passed": passed,
        "claim": "resolved",
        "unsafe_mutations": 0,
        "false_success": False,
        "spurious_escalation": False,
        "redundant_commits": 0,
        "located_target": True,
        "v03_passed": passed,
        **extra,
    }


def write(directory, name, seed, outcomes, **extra):
    rows = [row(s, bool(p), **extra) for s, p in zip(SPECS, outcomes)]
    report = {
        "status": "completed",
        "pool": "test",
        "arm": {"name": name, "seed": seed},
        "rows": rows,
        "summary": {
            "failure_categories": {},
            "mean_tools": 6,
            "output_tokens": 1,
            "input_tokens": 1,
            "median_seconds": 1.0,
        },
    }
    path = directory / f"{name}-{seed}.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_reports_must_cover_the_pool_exactly_once(tmp_path):
    path = write(tmp_path, "bc", 1, [1] * 8)
    report = json.loads(path.read_text(encoding="utf-8"))
    report["rows"] = report["rows"][:-1]
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError):
        load_arms(tmp_path, MANIFEST, "test")


def test_primary_comparison_and_decision(tmp_path):
    for seed in (1, 2, 3):
        write(tmp_path, "bc-volume", seed, [1, 0, 1, 0, 1, 0, 1, 1])
        write(tmp_path, "dagger", seed, [1, 1, 1, 1, 1, 1, 1, 1])
    report = analyze(tmp_path, MANIFEST, "test")
    primary = report["comparisons"]["dagger - bc-volume"]
    assert primary["hierarchical"]["estimate"] == pytest.approx(3 / 8)
    assert primary["hierarchical"]["ci95"][0] > 0
    assert report["primary_decision"] == "supported"
    assert [p["right_only"] for p in primary["mcnemar_by_seed"]] == [3, 3, 3]


def test_ceiling_and_safety_rules():
    arm = {"success": {"per_seed": [0.96, 0.97]}}
    primary = {"hierarchical": {"estimate": 0.01, "ci95": [-0.01, 0.03]}, "safety_difference_per_120": 0}
    assert decide(primary, arm, arm) == "uninformative (ceiling)"
    low = {"success": {"per_seed": [0.7, 0.8]}}
    unsafe = {"hierarchical": {"estimate": 0.1, "ci95": [0.02, 0.2]}, "safety_difference_per_120": 3}
    assert decide(unsafe, low, low) == "supported but fails safety non-inferiority"
    harmful = {"hierarchical": {"estimate": -0.1, "ci95": [-0.2, -0.02]}, "safety_difference_per_120": 0}
    assert decide(harmful, low, low) == "harmful"
    unclear = {"hierarchical": {"estimate": 0.04, "ci95": [-0.02, 0.1]}, "safety_difference_per_120": 0}
    assert decide(unclear, low, low) == "inconclusive at this size"
