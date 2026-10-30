"""Dialect study plumbing without a GPU: assignment, training rows, DAgger labels, evaluation."""

import json
import zipfile
from pathlib import Path

import pytest

from resolvelab.casedesk.manifest import load_manifest
from resolvelab.dialects import Translator, dialect_actions, run_dialect_episode
from resolvelab.dialects.assignment import build_assignment, dialect_named, load_assignment
from resolvelab.dialects.data import dagger_rows, expert_rows, validate_rows
from resolvelab.dialects.evaluate import evaluate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(ROOT / "benchmarks/casedesk-v2.json")


@pytest.fixture(scope="module")
def assignment(manifest):
    return load_assignment(ROOT / "benchmarks/casedesk-dialects-v1.json", manifest)


def test_assignment_is_reproducible_and_split_safe(manifest, assignment):
    assert assignment == build_assignment(manifest)
    names = list(assignment["episodes"].values())
    assert len(set(names)) == len(names) == sum(len(v) for v in manifest["episodes"].values())
    for pool, specs in manifest["episodes"].items():
        split = "heldout-" if pool == "test" else "train-"
        assert all(assignment["episodes"][s["id"]].startswith(split) for s in specs)
    training = {
        assignment["episodes"][s["id"]]
        for p in ("train_core", "train_pool")
        for s in manifest["episodes"][p]
    }
    assert not training & {assignment["episodes"][s["id"]] for s in manifest["episodes"]["dev"]}


def test_assignment_pins_the_generated_dialects(manifest, assignment, tmp_path):
    path = tmp_path / "assignment.json"
    path.write_text(json.dumps(assignment | {"dialects_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="not reproducible"):
        load_assignment(path, manifest)


def test_multi_dialect_expert_rows_are_the_v04_states_and_actions(manifest, assignment):
    """bc-multi differs from v0.4 bc only in the contract surface: same rows, states, actions."""
    rows, episodes = expert_rows(manifest, assignment, "train_core")
    validate_rows(rows, manifest, "train", assignment)
    with zipfile.ZipFile(ROOT / "artifacts/v0.4/data.zip") as bundle:
        published = [json.loads(line) for line in bundle.read("bc/train.jsonl").decode().splitlines()]
    assert len(rows) == len(published) == 396
    assert len({r["dialect"] for r in rows}) == len(episodes) == 64
    for ours, theirs in zip(rows, published):
        assert (ours["spec_id"], ours["step"]) == (theirs["spec_id"], theirs["step"])
        translator = Translator(dialect_named(ours["dialect"]), seed=ours["spec_id"])
        assert translator.to_canonical(ours["target"]) == theirs["target"]
        assert json.loads(ours["target_text"]) == ours["target"]
        assert ours["messages"][0]["content"] != theirs["messages"][0]["content"]


class MangleFirstWrite:
    """A scripted learner: follows the teacher, mis-copies the first token, then claims success."""

    def __init__(self, spec):
        self.spec = spec

    def set_dialect(self, dialect):
        self.dialect = dialect
        written = dialect_actions(run_dialect_episode(self.spec, dialect))
        patch = next(i for i, a in enumerate(written) if a["name"] == dialect.tools["patch_ticket"])
        bad = json.loads(json.dumps(written[patch]))
        key = dialect.args["etag"]
        value = bad["arguments"][key]
        bad["arguments"][key] = value + 1 if isinstance(value, int) else value + "x"
        finish = {
            "name": dialect.tools["finish"],
            "arguments": {dialect.args["outcome"]: dialect.outcomes["resolved"]},
        }
        self.script = written[:patch] + [bad, finish]
        self.metadata = {"learner": "scripted"}

    def next(self, messages):
        return self.script.pop(0), {}, 0


def test_dagger_labels_learner_states_in_the_dialect(manifest, assignment):
    spec = manifest["episodes"]["train_pool"][0]
    learner = MangleFirstWrite(spec)
    rows, episodes = dagger_rows(manifest, assignment, "train_pool", learner, "scripted", limit=1)
    validate_rows(rows, manifest, "train", assignment)
    dialect = learner.dialect
    assert dialect.name == assignment["episodes"][spec["id"]]
    assert episodes[0]["labelled"] == len(rows) and not episodes[0]["learner_passed"]
    disagreements = [r for r in rows if not r["learner_agreed"]]
    write, recover = disagreements
    assert write["target"]["name"] == dialect.tools["patch_ticket"]
    assert (
        write["target"]["arguments"][dialect.args["etag"]]
        != write["learner_action"]["arguments"][dialect.args["etag"]]
    )
    # After the self-inflicted conflict the verified label is a fresh read, not a finish.
    assert recover["learner_action"]["name"] == dialect.tools["finish"]
    assert recover["target"]["name"] == dialect.tools["get_ticket"]
    assert all(json.loads(r["target_text"]) == r["target"] for r in rows)


def test_row_provenance_rejects_wrong_dialects_and_pools(manifest, assignment):
    rows, _ = expert_rows(manifest, assignment, "dev", limit=1)
    validate_rows(rows, manifest, "dev", assignment)
    with pytest.raises(ValueError):
        validate_rows(rows, manifest, "train", assignment)
    moved = [r | {"dialect": "train-999"} for r in rows]
    with pytest.raises(ValueError, match="assigned"):
        validate_rows(moved, manifest, "dev", assignment)
    with pytest.raises(ValueError, match="Only train/dev"):
        expert_rows(manifest, assignment, "test", limit=1)


def test_dialect_evaluation_reports_slices(manifest, assignment, tmp_path):
    arm = {"name": "teacher", "max_tools": 24}
    report = evaluate(manifest, assignment, "dev", arm, tmp_path / "teacher.json", limit=3)
    assert report["summary"]["passed"] == 3 and report["status"] == "completed"
    assert report["assignment_sha256"]
    for row in report["rows"]:
        assert row["dialect"] == assignment["episodes"][row["spec_id"]]
        assert {"token_style", "cursor_style", "time_unit", "conflict_code"} <= set(row)
