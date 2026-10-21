import copy

import pytest

from resolvelab.httpdesk.experiment import compare


def reports():
    base = {
        "status": "completed",
        "policy": "base",
        "total": 3,
        "source_sha256": "s",
        "manifest_sha256": "m",
        "split": "test",
        "config": {
            k: "same" for k in ("base", "revision", "max_output", "context", "max_tools", "decoder")
        },
        "model": {
            k: "same"
            for k in (
                "schema_sha256",
                "prompt_sha256",
                "protocol",
                "decoder_version",
                "thinking",
                "do_sample",
                "dtype",
                "retries",
                "force_json_field_order",
            )
        },
        "rows": [{"template": "one-family", "seed": s, "passed": s == 1} for s in (1, 2, 3)],
        "summary": {},
    }
    trained = copy.deepcopy(base)
    trained["policy"] = "sft"
    trained["rows"][0]["passed"] = False
    trained["rows"][1]["passed"] = True
    return base, trained


def test_paired_http_comparison_keeps_regressions_and_clusters_record_variants():
    result = compare(*reports())
    assert (result["wins"], result["regressions"], result["ties"]) == (1, 1, 1)
    assert result["templates"] == 1
    assert result["template_bootstrap_95ci"] == [0, 0]


@pytest.mark.parametrize(
    "change", ["prompt", "model", "budget", "decoder", "missing", "duplicate", "status", "policy"]
)
def test_mismatched_http_comparison_is_rejected(change):
    before, after = reports()
    if change == "prompt":
        after["model"]["prompt_sha256"] = "new"
    elif change == "model":
        after["config"]["revision"] = "new"
    elif change == "budget":
        after["config"]["max_tools"] = 100
    elif change == "decoder":
        after["model"]["force_json_field_order"] = False
    elif change == "missing":
        after["rows"].pop()
    elif change == "duplicate":
        after["rows"][0] = after["rows"][1]
    elif change == "status":
        after["status"] = "running"
    else:
        before["policy"] = "reference"
    with pytest.raises(ValueError):
        compare(before, after)
