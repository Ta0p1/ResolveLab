"""``casedesk eval --workers``: concurrent episodes, the same report, and no local paths in it.

The scripted teacher stands in for a model, so the comparisons below run the real HTTP
environment and the real grader; only timing may differ between worker counts.
"""

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

from resolvelab.casedesk import cli, parallel
from resolvelab.casedesk.evaluate import evaluate as locked_evaluate
from resolvelab.casedesk.manifest import load_manifest
from resolvelab.casedesk.runner import run_episode
from resolvelab.policies import PolicyResponseError
from resolvelab.providers import CHECKOUT, make_provider, portable_path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = load_manifest(cli.MANIFEST)
DEV = [spec["id"] for spec in MANIFEST["episodes"]["dev"]]
TEACHER = make_provider("teacher")[1]
IDENTITY = ("manifest_sha256", "source_sha256", "pool", "arm", "arm_sha256", "adapter_sha256")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rows(report):
    # A row's trace_sha256 covers the trace's wall_seconds; the traces are compared without it.
    return [{k: v for k, v in r.items() if k not in ("seconds", "trace_sha256")} for r in report["rows"]]


def summary(report):
    return {k: v for k, v in report["summary"].items() if k != "median_seconds"}


def trace(report_path, name):
    value = load(Path(report_path).with_suffix("") / name)
    value.pop("wall_seconds")
    for decision in value["decisions"]:
        decision.pop("seconds", None)
    return value


def assert_same_evaluation(left, right):
    a, b = load(left), load(right)
    assert {k: a[k] for k in (*IDENTITY, "total", "status")} == {
        k: b[k] for k in (*IDENTITY, "total", "status")
    }
    assert rows(a) == rows(b) and summary(a) == summary(b)
    assert sorted(p.name for p in Path(left).with_suffix("").iterdir()) == sorted(
        p.name for p in Path(right).with_suffix("").iterdir()
    )
    for row in a["rows"]:
        assert trace(left, row["trace"]) == trace(right, row["trace"]), row["spec_id"]


def eval_args(output, *extra, model="teacher"):
    return ["eval", "--pool", "dev", "--model", model, "--output", str(output), *extra]


@pytest.fixture(scope="module")
def sequential(tmp_path_factory):
    """The teacher on the whole dev pool, one episode at a time."""
    output = tmp_path_factory.mktemp("sequential") / "teacher-dev.json"
    assert cli.main(eval_args(output)) == 0
    return output


def test_eight_workers_write_the_rows_and_traces_of_one(sequential, tmp_path):
    output = tmp_path / "teacher-dev.json"
    assert cli.main(eval_args(output, "--workers", "8")) == 0
    report = load(output)
    assert report["status"] == "completed" and report["summary"]["passed"] == len(DEV) == 40
    assert [r["spec_id"] for r in report["rows"]] == DEV
    assert_same_evaluation(sequential, output)


def test_one_worker_writes_what_casedesk_evaluate_writes(tmp_path):
    locked_evaluate(MANIFEST, "dev", TEACHER, tmp_path / "locked.json", limit=3)
    parallel.evaluate(MANIFEST, "dev", TEACHER, tmp_path / "parallel.json", limit=3)
    assert_same_evaluation(tmp_path / "locked.json", tmp_path / "parallel.json")
    assert load(tmp_path / "locked.json").keys() == load(tmp_path / "parallel.json").keys()


def test_rows_keep_manifest_order_when_episodes_finish_out_of_order(tmp_path, monkeypatch, capsys):
    others_done, lock, count = threading.Event(), threading.Lock(), [0]

    def first_finishes_last(spec, *args, **kwargs):
        if spec["id"] == DEV[0]:
            assert others_done.wait(timeout=60)
        result = run_episode(spec, *args, **kwargs)
        with lock:
            count[0] += 1
            if count[0] == 3:
                others_done.set()
        return result

    monkeypatch.setattr(parallel, "run_episode", first_finishes_last)
    report = parallel.evaluate(MANIFEST, "dev", TEACHER, tmp_path / "r.json", limit=4, workers=4)
    printed = [json.loads(line)["spec_id"] for line in capsys.readouterr().out.splitlines()]
    assert printed[-1] == DEV[0] and sorted(printed) == sorted(DEV[:4])
    assert [r["spec_id"] for r in report["rows"]] == DEV[:4]
    assert [r["spec_id"] for r in load(tmp_path / "r.json")["rows"]] == DEV[:4]


def test_an_interrupted_run_resumes_with_workers(sequential, tmp_path, monkeypatch):
    output = tmp_path / "teacher-dev.json"
    broken, ran = DEV[5], []

    def sandbox_lost(spec, *args, **kwargs):
        if spec["id"] == broken:
            raise RuntimeError("HTTP sandbox failed to start")
        return run_episode(spec, *args, **kwargs)

    monkeypatch.setattr(parallel, "run_episode", sandbox_lost)
    with pytest.raises(RuntimeError, match="sandbox"):
        cli.main(eval_args(output, "--limit", "12", "--workers", "4"))
    partial = load(output)
    done = [r["spec_id"] for r in partial["rows"]]
    assert partial["status"] == "running" and broken not in done
    assert done == [spec_id for spec_id in DEV if spec_id in done]  # manifest order

    with pytest.raises(ValueError, match="Existing or incompatible"):
        cli.main(eval_args(output, "--limit", "12", "--workers", "4"))

    def recorded(spec, *args, **kwargs):
        ran.append(spec["id"])
        return run_episode(spec, *args, **kwargs)

    monkeypatch.setattr(parallel, "run_episode", recorded)
    assert cli.main(eval_args(output, "--limit", "12", "--workers", "3", "--resume")) == 0
    report = load(output)
    assert sorted(ran) == sorted(set(DEV[:12]) - set(done))
    assert report["status"] == "completed" and [r["spec_id"] for r in report["rows"]] == DEV[:12]
    assert rows(report) == rows(load(sequential))[:12]
    for row in report["rows"]:
        assert trace(output, row["trace"]) == trace(sequential, row["trace"])


def test_hf_refuses_more_than_one_worker_before_loading_the_model(tmp_path, monkeypatch):
    def load_model(*_):
        pytest.fail("the hf model was loaded")

    monkeypatch.setattr("resolvelab.casedesk.policy.make_policy", load_model)
    output = tmp_path / "hf.json"
    with pytest.raises(SystemExit, match="one local GPU model") as stop:
        cli.main(eval_args(output, "--workers", "2", model="hf:Qwen/Qwen3-0.6B"))
    assert "--workers 1" in str(stop.value) and "openai:" in str(stop.value)
    assert not output.exists()
    with pytest.raises(ValueError, match="--workers 4 is not supported for hf:"):
        parallel.evaluate(MANIFEST, "dev", {"provider": "hf"}, output, workers=4)
    with pytest.raises(SystemExit) as stop:
        cli.main(eval_args(output, "--workers", "0"))
    assert stop.value.code == 2


class OneCallModel:
    """Fails each episode on its first call, after holding it long enough to overlap another."""

    def __init__(self, made):
        self.metadata, self.busy = {"provider": "fake"}, False
        made.append(self)

    def next(self, messages):
        assert not self.busy, "two running episodes share one provider instance"
        self.busy = True
        time.sleep(0.05)
        self.busy = False
        raise PolicyResponseError("not an action", {"failure_category": "json_error"}, 0.05)


def test_each_running_episode_has_a_provider_instance_of_its_own(tmp_path):
    made = []
    first = OneCallModel(made)
    arm = {"name": "fake", "provider": "fake", "max_tools": 24}
    report = parallel.evaluate(
        MANIFEST,
        "dev",
        arm,
        tmp_path / "r.json",
        first,
        limit=8,
        workers=4,
        spawn=lambda: OneCallModel(made),
    )
    assert len(made) == 4
    # A shared instance would have failed its overlap check, recorded as an inference_error.
    assert [r["error"] for r in report["rows"]] == ["json_error"] * 8
    assert report["model"] == {"provider": "fake"}

    def other():
        model = OneCallModel([])
        model.metadata = {"provider": "fake", "model": "other"}
        return model

    with pytest.raises(ValueError, match="disagree"):
        parallel.evaluate(MANIFEST, "dev", arm, tmp_path / "x.json", first, workers=2, spawn=other)
    with pytest.raises(ValueError, match="spawn"):
        parallel.evaluate(MANIFEST, "dev", arm, tmp_path / "y.json", first, workers=2)


class FakePolicy:
    """Stands in for the hf decoder: no weights, one failed call per episode."""

    def __init__(self, config, adapter=None):
        self.metadata = {
            "base": config["base"],
            "revision": config["revision"],
            "adapter": bool(adapter),
        }

    def next(self, messages):
        raise PolicyResponseError("not an action", {"failure_category": "json_error"}, 0)


def strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


def test_a_cli_report_records_no_local_path(tmp_path, monkeypatch):
    base = tmp_path / "models" / "Qwen3-0.6B"
    adapter = tmp_path / "runs" / "bc-42" / "epoch-3"
    base.mkdir(parents=True)
    adapter.mkdir(parents=True)
    (adapter / "adapter_model.safetensors").write_bytes(b"adapter weights")
    monkeypatch.setattr("resolvelab.casedesk.policy.make_policy", FakePolicy)
    output = tmp_path / "reports" / "hf-dev.json"
    args = eval_args(output, "--option", f"adapter={adapter}", "--limit", "2", model=f"hf:{base}")
    assert cli.main(args) == 0

    report = load(output)
    sha256 = hashlib.sha256(b"adapter weights").hexdigest()
    assert report["arm"]["adapter"] == "epoch-3"
    assert report["arm"]["adapter_sha256"] == report["adapter_sha256"] == sha256
    assert report["arm"]["base"] == report["model"]["base"] == "Qwen3-0.6B"
    assert report["arm"]["name"] == "hf:Qwen3-0.6B" and report["arm"]["model"] == "Qwen3-0.6B"
    files = [output, *output.with_suffix("").iterdir()]
    assert len(files) == 3
    markers = (":\\", "/mnt/", "/home/", "Users", str(tmp_path), tmp_path.as_posix())
    for path in files:
        for text in strings(load(path)):
            assert not [m for m in markers if m in text], (path.name, text)

    # The same run resumes: the recorded identity does not depend on where the files are.
    report["status"] = "running"
    output.write_text(json.dumps(report), encoding="utf-8")
    assert cli.main([*args, "--resume"]) == 0


def test_a_local_adapter_inside_the_checkout_is_recorded_relative_to_it(tmp_path, monkeypatch):
    assert CHECKOUT == ROOT
    monkeypatch.setattr("resolvelab.providers.CHECKOUT", tmp_path)
    monkeypatch.setattr("resolvelab.casedesk.policy.make_policy", FakePolicy)
    adapter = tmp_path / ".local" / "runs" / "bc-42"
    adapter.mkdir(parents=True)
    (adapter / "adapter_model.safetensors").write_bytes(b"w")
    _, arm = make_provider("hf:Qwen/Qwen3-0.6B", {"adapter": str(adapter)})
    assert arm["adapter"] == ".local/runs/bc-42"
    assert arm["adapter_sha256"] == hashlib.sha256(b"w").hexdigest()
    # A Hub id is not a path and is recorded as given.
    assert (arm["name"], arm["model"], arm["base"]) == ("hf:Qwen/Qwen3-0.6B",) + ("Qwen/Qwen3-0.6B",) * 2
    assert portable_path(tmp_path.parent / "elsewhere" / "lora", tmp_path) == "lora"

    (tmp_path / "empty").mkdir()
    monkeypatch.setattr("resolvelab.casedesk.policy.make_policy", lambda *_: pytest.fail("loaded"))
    with pytest.raises(ValueError, match="adapter_model.safetensors"):
        make_provider("hf:Qwen/Qwen3-0.6B", {"adapter": str(tmp_path / "empty")})
