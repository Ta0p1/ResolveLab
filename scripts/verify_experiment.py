"""Audit published metrics, hashes and tool trajectories without downloading a model."""

import json
import tempfile
from pathlib import Path

from resolvelab.benchmark import cases, digest, load_manifest, validate_training_rows
from resolvelab.curation import read_rows
from resolvelab.experiments import compare
from resolvelab.store import Store
from resolvelab.tools import Toolbox
from resolvelab.training import file_hash
from resolvelab.verification import grade

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts/v0.2"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify():
    manifest = load_manifest(ROOT / "benchmarks/composition-v1.json")
    base, sft = [read(ARTIFACTS / f"{p}-test.json") for p in ("base", "sft")]
    comparison = read(ARTIFACTS / "comparison.json")
    assert compare(base, sft) == comparison, "Published comparison differs from its source rows"
    control_base, control_sft = [read(ARTIFACTS / f"{p}-format-test.json") for p in ("base", "sft")]
    control_comparison = read(ARTIFACTS / "format-comparison.json")
    assert compare(control_base, control_sft) == control_comparison
    training = read(ARTIFACTS / "training.json")
    assert training["status"] == "completed"
    assert training["manifest_sha256"] == digest(manifest)
    selected = min(training["epochs"], key=lambda e: e["dev_loss"])
    assert selected["checkpoint"] == training["selected_checkpoint"]
    assert selected["adapter_sha256"] == sft["adapter_sha256"]
    assert selected["adapter_sha256"] == control_sft["adapter_sha256"]
    for split in ("train", "dev"):
        path = ARTIFACTS / "data" / f"{split}.jsonl"
        validate_training_rows(read_rows(path), manifest, split)
        assert file_hash(path) == training["portable_data_sha256"][split]
    specs = {(spec.id, seed): spec for spec, seed in cases(manifest, "test")}
    episodes = 0
    with tempfile.TemporaryDirectory() as temp:
        store = Store(Path(temp) / "replay.sqlite")
        for report in (base, sft, control_base, control_sft, read(ARTIFACTS / "reference-test.json")):
            assert report["manifest_sha256"] == digest(manifest)
            assert {(r["scenario"], r["seed"]) for r in report["rows"]} == specs.keys()
            for row in report["rows"]:
                path = (ARTIFACTS / row["trace"]).resolve()
                assert path.is_relative_to(ARTIFACTS.resolve())
                assert file_hash(path) == row["trace_sha256"]
                trace = read_rows(path)
                assert trace[0]["id"] == row["id"] and trace[0]["verdict"] == row["verdict"]
                spec = specs[(row["scenario"], row["seed"])]
                run_id = store.create(spec.id, row["seed"], spec=spec)
                tools = Toolbox(store, run_id)
                for event in trace[1:]:
                    if event["kind"] != "tool":
                        continue
                    actual = tools.call(event["name"], event["arguments"])
                    expected = {k: v for k, v in event["result"].items() if k != "mutated"}
                    if event["name"] == "escalate":
                        actual.pop("ticket", None)
                        expected.pop("ticket", None)
                    assert actual == expected, (row["scenario"], event["name"])
                with store.connect() as connection:
                    actual = grade(connection, run_id, row["claim"])
                assert actual == row["verdict"], (row["scenario"], "replayed verdict")
                episodes += 1
    evidence = read(ROOT / "src/resolvelab/static/experiment.json")
    assert evidence == {
        "comparison": comparison,
        "training": training,
        "manifest": manifest,
        "base": base,
        "sft": sft,
        "format_control": {"base": control_base, "sft": control_sft, "comparison": control_comparison},
    }
    print(
        f"Verified split boundaries, adapter selection, metrics and {episodes} executable trace replays."
    )


if __name__ == "__main__":
    verify()
