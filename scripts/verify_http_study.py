"""GPU-free audit: validate provenance and replay every published action over real HTTP."""

import json
import tempfile
from pathlib import Path

from resolvelab.benchmark import digest
from resolvelab.httpdesk.benchmark import cases, load_manifest, validate_rows
from resolvelab.httpdesk.experiment import collect, compare, episode, summarize
from resolvelab.httpdesk.schema import validate_action
from resolvelab.training import file_hash

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts/v0.3"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify():
    manifest = load_manifest(ROOT / "benchmarks/httpdesk-v1.json")
    lock = read(BUNDLE / "test-lock.json")
    assert digest(manifest) == lock["manifest_sha256"]
    config = read(ROOT / "benchmarks/httpdesk-sft-v1.json")
    assert digest(config) == lock["config_sha256"]
    training_lock = read(BUNDLE / "training-lock.json")
    for split in ("train", "dev"):
        path = BUNDLE / "data" / f"{split}.jsonl"
        assert file_hash(path) == lock["data_sha256"][split]
        validate_rows(
            [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()], manifest, split
        )
    with tempfile.TemporaryDirectory() as directory:
        regenerated = Path(directory) / "data"
        collect(manifest, regenerated)
        for split in ("train", "dev"):
            assert file_hash(regenerated / f"{split}.jsonl") == lock["data_sha256"][split]
    templates = {t["id"]: t for t in manifest["splits"]["test"]["templates"]}
    expected = {(t["id"], seed) for t, seed in cases(manifest, "test")}
    reports = {}
    replayed = 0
    names = ["base-test", "large-test", *[f"sft-{s}-test" for s in config["training_seeds"]]]
    for name in names:
        report = read(BUNDLE / f"{name}.json")
        assert report["status"] == "completed" and report["split"] == "test"
        assert report["created_at"] > lock["locked_at"]
        assert digest(report["config"]) == report["config_sha256"]
        expected_config = dict(config)
        if name == "large-test":
            expected_config.update(config["larger_baseline"])
        elif name.startswith("sft-"):
            expected_config["seed"] = int(name.split("-")[1])
        assert report["config"] == expected_config
        assert report["total"] == len(report["rows"]) == len(expected)
        assert {(r["template"], r["seed"]) for r in report["rows"]} == expected
        assert report["summary"] == summarize(report["rows"])
        for key in ("source_sha256", "manifest_sha256"):
            assert report[key] == lock[key]
        for key in ("prompt_sha256", "schema_sha256"):
            assert report["model"][key] == lock[key]
        assert report["model"]["force_json_field_order"] is True
        assert report["model"]["state_dependent_constraints"] is False
        for row in report["rows"]:
            path = BUNDLE / name / row["trace"]
            assert file_hash(path) == row["trace_sha256"]
            trace = read(path)
            assert trace["training_eligible"] is False
            for key, value in trace["verdict"].items():
                assert row[key] == value
            decisions = trace["decisions"]
            assert row["decisions"] == len(decisions)
            assert row["tools"] == len(trace["observations"])
            assert row["json_valid"] == sum(d["usage"].get("json_valid", False) for d in decisions)
            assert row["schema_valid"] == sum(d["usage"].get("schema_valid", False) for d in decisions)
            for d in decisions:
                if "action" in d:
                    assert (
                        validate_action(json.loads(d["usage"]["raw_output"])).model_dump() == d["action"]
                    )
            actions = [d["action"] for d in decisions if "action" in d]
            replay = episode(
                templates[row["template"]],
                row["seed"],
                max_tools=report["config"]["max_tools"],
                replay=actions,
            )
            for key in (
                "task",
                "observations",
                "http_client",
                "http_server",
                "initial_state",
                "final_state",
                "commits",
                "verdict",
            ):
                assert replay[key] == trace[key], (name, row["trace"], key)
            replayed += 1
        reports[name] = report
    for seed in config["training_seeds"]:
        training = read(BUNDLE / f"training-{seed}.json")
        assert training["status"] == "completed"
        assert training["source_sha256"] == training_lock["source_sha256"]
        assert training["manifest_sha256"] == lock["manifest_sha256"]
        assert training["finished_at"] < lock["locked_at"]
        assert training["config"]["seed"] == seed
        selected = min(training["epochs"], key=lambda e: e["dev_loss"])
        assert selected["checkpoint"] == training["selected_checkpoint"]
        assert selected["adapter_sha256"] == lock["selected_adapters"][str(seed)]["sha256"]
        assert (
            file_hash(BUNDLE / f"training-{seed}.json")
            == lock["selected_adapters"][str(seed)]["training_report_sha256"]
        )
        assert training["data_sha256"] == lock["data_sha256"]
        trained = reports[f"sft-{seed}-test"]
        assert trained["adapter_sha256"] == selected["adapter_sha256"]
        assert compare(reports["base-test"], trained) == read(BUNDLE / f"comparison-{seed}.json")
    evidence = read(ROOT / "src/resolvelab/static/http-experiment.json")
    assert evidence["reports"] == reports
    assert evidence["lock"] == lock
    print(
        f"Verified hashes, split provenance, 3 checkpoint selections and {replayed} real-HTTP episode replays."
    )


if __name__ == "__main__":
    verify()
