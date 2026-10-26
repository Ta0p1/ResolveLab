"""GPU-free audit: validate provenance and replay every published action over real HTTP."""

import hashlib
import json
import tempfile
from itertools import combinations
from pathlib import Path

from resolvelab.benchmark import digest
from resolvelab.httpdesk.benchmark import cases, load_manifest, validate_rows
from resolvelab.httpdesk.experiment import collect, compare, episode, summarize
from resolvelab.httpdesk.schema import action_schema, initial_messages, validate_action
from resolvelab.httpdesk.service import DeskState
from resolvelab.training import file_hash

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts/v0.3"
PACKAGE = ROOT / "src/resolvelab"
# Exactly the files `httpdesk.benchmark.source_hash()` covered at the v0.3.0 tag. Later
# versions add modules, so the whole-package hash moves on, but none of these may change.
V03_SOURCE = (
    "__init__.py api.py benchmark.py cli.py curation.py evaluation.py experiments.py "
    "hf_policy.py httpdesk/__init__.py httpdesk/adapter.py httpdesk/benchmark.py "
    "httpdesk/demo.json httpdesk/experiment.py httpdesk/grading.py httpdesk/policy.py "
    "httpdesk/reference.py httpdesk/schema.py httpdesk/service.py policies.py runner.py "
    "scenarios.py store.py tools.py training.py verification.py"
).split()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def frozen_source_hash():
    """The v0.3 source_hash algorithm, restricted to the files that existed at v0.3.0."""
    h = hashlib.sha256()
    for name in sorted(V03_SOURCE, key=lambda n: tuple(n.split("/"))):
        h.update(name.encode())
        h.update((PACKAGE / name).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def verify():
    manifest = load_manifest(ROOT / "benchmarks/httpdesk-v1.json")
    records = {
        split: [DeskState([], seed) for seed in part["seeds"]]
        for split, part in manifest["splits"].items()
    }
    for left, right in combinations(records.values(), 2):
        assert not ({s.reference for s in left} & {s.reference for s in right})
        assert not ({key for s in left for key in s.tickets} & {key for s in right for key in s.tickets})
    lock = read(BUNDLE / "test-lock.json")
    assert frozen_source_hash() == lock["source_sha256"]
    assert digest(initial_messages("TASK_PLACEHOLDER")) == lock["prompt_sha256"]
    assert digest(action_schema()) == lock["schema_sha256"]
    assert digest(manifest) == lock["manifest_sha256"]
    config = read(ROOT / "benchmarks/httpdesk-sft-v1.json")
    assert digest(config) == lock["config_sha256"]
    training_lock = read(BUNDLE / "training-lock.json")
    for key in (
        "source_sha256",
        "manifest_sha256",
        "config_sha256",
        "prompt_sha256",
        "schema_sha256",
        "data_sha256",
    ):
        assert training_lock[key] == lock[key]
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
    names.append("ollama-4b-test")
    for name in names:
        report = read(BUNDLE / f"{name}.json")
        assert report["status"] == "completed" and report["split"] == "test"
        assert report["created_at"] > lock["locked_at"]
        assert digest(report["config"]) == report["config_sha256"]
        expected_config = dict(config)
        if name == "ollama-4b-test":
            expected_config = read(ROOT / "benchmarks/httpdesk-ollama-control.json")
            assert digest(expected_config) == lock["ollama_control_config_sha256"]
            assert report["script_sha256"] == lock["ollama_control_script_sha256"]
            assert report["script_sha256"] == file_hash(ROOT / "scripts/http_ollama_control.py")
            assert report["model"]["digest"] == expected_config["digest"]
        elif name == "large-test":
            expected_config.update(config["larger_baseline"])
        elif name.startswith("sft-"):
            expected_config["seed"] = int(name.split("-")[1])
        assert report["config"] == expected_config
        assert report["total"] == len(report["rows"]) == len(expected)
        assert {(r["template"], r["seed"]) for r in report["rows"]} == expected
        assert report["summary"] == summarize(report["rows"])
        for key in ("source_sha256", "manifest_sha256"):
            assert report[key] == lock[key]
        assert report["model"]["schema_sha256"] == lock["schema_sha256"]
        if name == "ollama-4b-test":
            assert report["model"]["base_prompt_sha256"] == lock["prompt_sha256"]
            assert report["model"]["prompt_sha256"] == digest(
                {
                    "base_prompt": initial_messages("TASK_PLACEHOLDER"),
                    "system_addendum": expected_config["system_addendum"],
                    "observation_reminder": expected_config["observation_reminder"],
                }
            )
        else:
            assert report["model"]["prompt_sha256"] == lock["prompt_sha256"]
        if name != "ollama-4b-test":
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
            for key in ("input_tokens", "output_tokens"):
                assert row[key] == sum(d["usage"].get(key, 0) for d in decisions)
            assert row["seconds"] == trace["wall_seconds"]
            assert row["error"] == trace["error"]
            assert row["http_statuses"] == [
                o["result"]["status"] for o in trace["observations"] if "status" in o["result"]
            ]
            for d in decisions:
                usage = d["usage"]
                if "raw_output" in usage and usage.get("failure_category") != "context_limit":
                    json_valid, schema_valid = False, False
                    try:
                        parsed = json.loads(usage["raw_output"])
                        json_valid = True
                        validate_action(parsed)
                        schema_valid = True
                    except (ValueError, TypeError):
                        pass
                    assert usage["json_valid"] == json_valid
                    assert usage["schema_valid"] == schema_valid
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
    assert evidence["supplementary"] == reports.pop("ollama-4b-test")
    assert evidence["reports"] == reports
    assert evidence["lock"] == lock
    assert evidence["manifest"] == manifest
    assert evidence["training"] == {
        str(seed): read(BUNDLE / f"training-{seed}.json") for seed in config["training_seeds"]
    }
    assert set(evidence["previews"]) == set(reports) | {"ollama-4b-test"}
    for name, previews in evidence["previews"].items():
        report = evidence["supplementary"] if name == "ollama-4b-test" else reports[name]
        assert set(previews) == {row["trace"] for row in report["rows"]}
        for file, preview in previews.items():
            trace = read(BUNDLE / name / file)
            assert preview == {
                key: trace[key]
                for key in (
                    "task",
                    "verdict",
                    "observations",
                    "http_client",
                    "initial_state",
                    "final_state",
                )
            }
    print(
        f"Verified hashes, split provenance, 3 checkpoint selections and {replayed} real-HTTP episode replays."
    )


if __name__ == "__main__":
    verify()
