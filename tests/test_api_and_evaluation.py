import json
import time

from fastapi.testclient import TestClient

from resolvelab.api import create_app
from resolvelab.evaluation import evaluate, export_trace, new_report
from resolvelab.policies import OllamaPolicy, decision
from resolvelab.runner import Runner
from resolvelab.store import Store


def wait_for(client, url, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(url).json()
        if body["status"] not in {"running", "queued"}:
            return body
        time.sleep(0.02)
    raise AssertionError(f"Timeout waiting for {url}")


def test_http_run_evaluation_and_export(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/api/health").json()["ok"]
        scenarios = client.get("/api/scenarios").json()
        assert len(scenarios) == 10
        assert all("faults" not in scenario for scenario in scenarios)
        response = client.post("/api/runs", json={"scenario": "compound"})
        assert response.status_code == 201
        run_id = response.json()["id"]
        run = wait_for(client, f"/api/runs/{run_id}")
        assert run["verdict"]["passed"]
        lines = client.get(f"/api/runs/{run_id}/trace").text.splitlines()
        assert json.loads(lines[0])["training_eligible"] is False
        assert len(lines) > 5
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 409
        ev = client.post("/api/evaluations", json={"suite": "smoke"})
        assert ev.status_code == 201
        report = wait_for(client, f"/api/evaluations/{ev.json()['id']}")
        assert report["completed"] == 6
        assert report["status"] == "completed"


def test_invalid_requests_and_cross_origin_are_rejected(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.post("/api/runs", json={"scenario": "absent"}).status_code == 422
        assert client.post("/api/runs", json={"scenario": "partial_sync", "seed": -1}).status_code == 422
        assert client.get("/api/runs/absent").status_code == 404
        response = client.post(
            "/api/runs",
            json={"scenario": "partial_sync"},
            headers={"Origin": "https://attacker.example"},
        )
        assert response.status_code == 403
        assert client.get("/api/runs").json() == []


def test_local_provider_failure_counts_as_failed_episode(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionError("Local inference unavailable")

    monkeypatch.setattr(OllamaPolicy, "next", unavailable)
    monkeypatch.setattr("resolvelab.evaluation.model_metadata", lambda _: {"name": "test"})
    runner = Runner(Store(tmp_path / "test.sqlite"))
    report = new_report(["ollama"], ["partial_sync"], [42], "test")
    evaluate(runner, report, tmp_path / "report.json", "test")
    assert report["status"] == "completed"
    assert report["completed"] == 1
    assert report["summary"][0]["episodes"] == 1
    assert report["summary"][0]["passed"] == 0
    assert report["summary"][0]["errors"] == 1


def test_provider_receives_only_observations_and_no_rule_fallback(tmp_path, monkeypatch):
    seen = []
    actions = iter(
        [
            decision("inspect_job"),
            decision("finish", claim="resolved", summary="Unsupported claim"),
        ]
    )

    def fake_next(self, messages):
        seen.append(json.loads(json.dumps(messages)))
        return next(actions), {"input_tokens": 10, "output_tokens": 4}, 0.01

    monkeypatch.setattr(OllamaPolicy, "next", fake_next)
    store = Store(tmp_path / "test.sqlite")
    run = Runner(store).execute(store.create("lost_response", policy="ollama", model="test"))
    assert not run["verdict"]["passed"]
    assert run["verdict"]["false_success"]
    assert run["input_tokens"] == 20
    assert run["output_tokens"] == 8
    conversation = json.dumps(seen)
    for hidden in ("fault_consumed", "initial_destination", '"mutated"', "lost_response"):
        assert hidden not in conversation
    assert all(e["name"] != "sync_records" for e in run["events"])
    assert json.loads(export_trace(store, run["id"]).splitlines()[0])["policy"] == "ollama"


def test_report_creation_failure_does_not_permanently_lock_evaluation(tmp_path, monkeypatch):
    from resolvelab import api

    original = api.write_report

    def disk_full(*args):
        raise OSError("Disk is full")

    with TestClient(create_app(tmp_path), raise_server_exceptions=False) as client:
        monkeypatch.setattr(api, "write_report", disk_full)
        assert client.post("/api/evaluations", json={"suite": "smoke"}).status_code == 500
        monkeypatch.setattr(api, "write_report", original)
        response = client.post("/api/evaluations", json={"suite": "smoke"})
        assert response.status_code == 201
        assert wait_for(client, f"/api/evaluations/{response.json()['id']}")["status"] == "completed"
