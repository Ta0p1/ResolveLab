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


# -- lock and audit -------------------------------------------------------------------------


def test_source_hash_ignores_only_the_version_line(tmp_path):
    from resolvelab.dialects.lock import source_hash

    (tmp_path / "__init__.py").write_bytes(b'"""Pkg."""\n__version__ = "0.4.0"\n')
    (tmp_path / "mod.py").write_bytes(b"X = 1\r\n")
    before = source_hash(["__init__.py", "mod.py"], tmp_path)
    (tmp_path / "__init__.py").write_bytes(b'"""Pkg."""\n__version__ = "0.5.0"\n')
    (tmp_path / "mod.py").write_bytes(b"X = 1\n")
    assert source_hash(["__init__.py", "mod.py"], tmp_path) == before
    (tmp_path / "mod.py").write_bytes(b"X = 2\n")
    assert source_hash(["__init__.py", "mod.py"], tmp_path) != before
    (tmp_path / "__init__.py").write_bytes(b'"""Pkg."""\n')
    with pytest.raises(ValueError, match="__version__"):
        source_hash(["__init__.py"], tmp_path)


def fake_run(directory, checkpoint="epoch-2", status="completed"):
    (directory / checkpoint).mkdir(parents=True)
    (directory / checkpoint / "adapter_model.safetensors").write_bytes(directory.name.encode())
    report = {
        "status": status,
        "selected_checkpoint": checkpoint,
        "data_sha256": {},
        "examples": {},
        "epochs": [],
    }
    (directory / "training.json").write_text(json.dumps(report), encoding="utf-8")


def test_lock_pins_v04_and_new_adapters_and_refuses_late_or_incomplete_runs(
    manifest, assignment, tmp_path
):
    from resolvelab.dialects.audit import verify_inputs
    from resolvelab.dialects.lock import build_lock

    v04 = json.loads((ROOT / "artifacts/v0.4/test-lock.json").read_text(encoding="utf-8"))
    for arm in ("bc-multi", "bc-volume-multi", "dagger-multi"):
        fake_run(tmp_path / "runs" / f"{arm}-42")
    options = dict(
        local=tmp_path,
        manifest=manifest,
        assignment=assignment,
        study={"name": "draft"},
        v04_lock=v04,
        commit="abc",
        locked_at="2026-10-30T00:00:00+00:00",
        seeds=[42],
    )
    lock = build_lock(**options)
    assert lock["adapters"]["dagger-42"]["sha256"] == v04["adapters"]["dagger-42"]["sha256"]
    assert lock["adapters"]["dagger-multi-42"]["checkpoint"] == "epoch-2"
    verify_inputs(lock, manifest, assignment, {"name": "draft"})
    with pytest.raises(AssertionError):
        verify_inputs(lock | {"schemas_sha256": "0" * 64}, manifest, assignment, {"name": "draft"})
    (tmp_path / "eval/test").mkdir(parents=True)
    (tmp_path / "eval/test/early.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="precede"):
        build_lock(**options)
    (tmp_path / "eval/test/early.json").unlink()
    (tmp_path / "eval/study-contract").mkdir(parents=True)
    (tmp_path / "eval/study-contract/early.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="precede"):
        build_lock(**options)
    (tmp_path / "eval/study-contract/early.json").unlink()
    fake_run(tmp_path / "runs" / "unfinished", status="running")
    (tmp_path / "runs" / "bc-multi-42").rename(tmp_path / "runs" / "old")
    (tmp_path / "runs" / "unfinished").rename(tmp_path / "runs" / "bc-multi-42")
    with pytest.raises(ValueError, match="incomplete"):
        build_lock(**options)


def test_audit_regenerates_expert_rows_and_rederives_dagger_labels(manifest, assignment):
    from resolvelab.dialects.audit import verify_dagger_rows, verify_expert_rows
    from resolvelab.store import dumps

    rows, _ = expert_rows(manifest, assignment, "dev", limit=2)
    published = "".join(dumps(r) + "\n" for r in rows).encode()
    assert verify_expert_rows(manifest, assignment, "dev", published, limit=2) == len(rows)
    with pytest.raises(AssertionError):
        verify_expert_rows(
            manifest, assignment, "dev", published.replace(b'"step": 1', b'"step": 9'), limit=2
        )
    spec = manifest["episodes"]["train_pool"][0]
    labelled, _ = dagger_rows(
        manifest, assignment, "train_pool", MangleFirstWrite(spec), "scripted", limit=1
    )
    assert verify_dagger_rows(manifest, labelled) == len(labelled)
    wrong = json.loads(json.dumps(labelled))
    wrong[-1]["target"] = wrong[-1]["learner_action"]
    with pytest.raises(AssertionError):
        verify_dagger_rows(manifest, wrong)


def test_audit_replays_reports_in_their_dialects(manifest, assignment, tmp_path):
    from resolvelab.dialects.audit import verify_reports

    output = tmp_path / "teacher.json"
    report = evaluate(manifest, assignment, "dev", {"name": "teacher", "max_tools": 24}, output, limit=2)
    lock = {k: report[k] for k in ("manifest_sha256", "assignment_sha256", "source_sha256")}
    lock |= {"locked_at": "2026-01-01T00:00:00+00:00", "adapters": {}}

    def read_trace(report, row):
        return (tmp_path / "teacher" / row["trace"]).read_bytes()

    assert verify_reports([report], read_trace, manifest, assignment, lock) == 2
    with pytest.raises(AssertionError):
        verify_reports([report], read_trace, manifest, assignment, lock | {"locked_at": "2999"})
    path = tmp_path / "teacher" / report["rows"][0]["trace"]
    path.write_bytes(path.read_bytes().replace(b'"passed": true', b'"passed": false', 1))
    with pytest.raises(AssertionError):
        verify_reports([report], read_trace, manifest, assignment, lock)


def test_study_contract_evaluation_runs_and_replays_in_the_canonical_dialect(
    manifest, assignment, tmp_path
):
    from resolvelab.dialects.audit import verify_reports

    arm = {"name": "teacher", "max_tools": 24}
    output = tmp_path / "teacher.json"
    report = evaluate(manifest, assignment, "dev", arm, output, limit=2, contract="study")
    assert report["contract"] == "study" and report["summary"]["passed"] == 2
    assert {(r["dialect"], r["token_style"], r["conflict_code"]) for r in report["rows"]} == {
        ("canonical", "etag", 412)
    }
    lock = {k: report[k] for k in ("manifest_sha256", "assignment_sha256", "source_sha256")}
    lock |= {"locked_at": "2026-01-01T00:00:00+00:00", "adapters": {}}

    def read_trace(report, row):
        return (tmp_path / "teacher" / row["trace"]).read_bytes()

    assert verify_reports([report], read_trace, manifest, assignment, lock) == 2
    with pytest.raises(AssertionError):
        verify_reports([report | {"contract": "assigned"}], read_trace, manifest, assignment, lock)
    with pytest.raises(ValueError, match="Unknown contract"):
        evaluate(manifest, assignment, "dev", arm, tmp_path / "x.json", limit=1, contract="other")
    assert not (tmp_path / "x.json").exists()


@pytest.mark.parametrize(
    "command",
    [
        ["collect-expert", "--pool", "test"],
        ["eval", "--pool", "test", "--arm", "bc", "--seed", "42", "--adapter", "{adapter}"],
        ["eval", "--pool", "test", "--arm", "base-0.6b"],
    ],
)
def test_pipeline_opens_the_test_pool_only_for_locked_evaluations(tmp_path, command):
    import os
    import subprocess
    import sys

    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapter_model.safetensors").write_bytes(b"not a locked adapter")
    output = tmp_path / "report.json"
    command = [part.format(adapter=adapter) for part in command] + ["--output", str(output)]
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    done = subprocess.run(
        [sys.executable, "scripts/dialect_transfer.py", *command],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        timeout=120,
    )
    assert done.returncode != 0 and not output.exists()
    assert any(
        reason in done.stderr
        for reason in ("evaluation only", "test lock", "base-1.7b", "does not match")
    ), done.stderr


def test_audit_comparison_tolerates_only_float_rounding():
    from resolvelab.dialects.audit import same

    same({"a": [1, 0.1 + 0.2], "b": "x"}, {"a": [1, 0.3], "b": "x"})
    for changed in ({"a": [2, 0.3], "b": "x"}, {"a": [1, 0.31], "b": "x"}, {"a": [1, 0.3]}):
        with pytest.raises(AssertionError):
            same(changed, {"a": [1, 0.3], "b": "x"})
