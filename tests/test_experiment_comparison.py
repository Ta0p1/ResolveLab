import copy

import pytest

from resolvelab.experiments import compare


def pair():
    base = {
        "manifest_sha256": "same",
        "config_sha256": "same",
        "split": "test",
        "source_sha256": "same",
        "max_tools": 18,
        "status": "completed",
        "total": 3,
        "policy": "hf-base",
        "model": {"adapter": False, "prompt_sha256": "same"},
        "rows": [{"scenario": "a", "seed": s, "verdict": {"passed": s == 1}} for s in (1, 2, 3)],
        "summary": [],
    }
    after = copy.deepcopy(base)
    after["policy"] = "hf-sft"
    after["model"]["adapter"] = True
    after["rows"][0]["verdict"]["passed"] = False
    after["rows"][1]["verdict"]["passed"] = True
    return base, after


def test_paired_comparison_preserves_regressions_and_correlated_template():
    result = compare(*pair())
    assert (result["wins"], result["regressions"], result["ties"]) == (1, 1, 1)
    assert result["pass_rate_delta"] == 0
    assert result["templates"] == 1
    assert result["template_bootstrap_95_interval"] == [0, 0]


@pytest.mark.parametrize("change", ["prompt", "config", "missing", "duplicate", "incomplete"])
def test_incompatible_comparisons_are_rejected(change):
    before, after = pair()
    if change == "prompt":
        after["model"]["prompt_sha256"] = "different"
    elif change == "config":
        after["config_sha256"] = "different"
    elif change == "missing":
        after["rows"][0]["seed"] = 9
    elif change == "duplicate":
        after["rows"][0] = after["rows"][1]
    else:
        after["status"] = "running"
    with pytest.raises(ValueError):
        compare(before, after)
