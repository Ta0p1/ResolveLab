import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from resolvelab.runner import Runner
from resolvelab.scenarios import BY_ID
from resolvelab.store import Store
from resolvelab.tools import Toolbox
from resolvelab.verification import grade


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.sqlite")


def verdict(store, run_id, claim="resolved"):
    with store.connect() as connection:
        return grade(connection, run_id, claim)


@pytest.mark.parametrize("scenario", list(BY_ID))
@pytest.mark.parametrize("seed", [7, 42, 101])
def test_runbook_recovers_or_correctly_escalates(store, scenario, seed):
    run = Runner(store).execute(store.create(scenario, seed))
    assert run["status"] == "completed"
    assert run["verdict"]["passed"]
    assert not run["verdict"]["false_success"]
    assert run["verdict"]["duplicate_count"] == 0


def test_fabricated_success_and_stale_status_do_not_pass(store):
    run_id = store.create("stale_status")
    tools = Toolbox(store, run_id)
    assert tools.call("inspect_job", {})["job_status"] == "completed"
    tools.call("finish", {"claim": "resolved", "summary": "Everything is fixed."})
    result = verdict(store, run_id)
    assert result["false_success"]
    assert not result["passed"]
    assert result["missing_count"] > 0


def test_success_requires_verification_after_last_write(store):
    run_id = store.create("partial_sync")
    tools = Toolbox(store, run_id)
    tools.call("sync_records", {"mode": "upsert", "idempotency_key": "a"})
    assert verdict(store, run_id)["exact_match"]
    assert not verdict(store, run_id)["passed"]
    tools.call("verify_sync", {})
    assert verdict(store, run_id)["passed"]
    tools.call("configure_sync", {"key_field": "legacy_id"})
    assert not verdict(store, run_id)["verified_after_last_write"]


def test_lost_ack_receipt_survives_new_store_and_prevents_duplicate_retry(store):
    run_id = store.create("lost_response")
    tools = Toolbox(store, run_id)
    args = {"mode": "append", "idempotency_key": "same-request"}
    result = tools.call("sync_records", args)
    assert result["error"] == "response_lost"
    assert "mutated" not in result
    before = store.get(run_id)["destination_count"]
    reopened = Store(store.path)
    retried = Toolbox(reopened, run_id).call("sync_records", args)
    assert retried["replayed"] and retried["complete"]
    assert reopened.get(run_id)["destination_count"] == before
    # An idempotency receipt prevents retry duplication, but append itself was unsafe.
    assert verdict(store, run_id)["duplicate_count"] > 0


def test_partial_commit_requires_reconciliation_and_new_operation(store):
    run_id = store.create("partial_commit")
    tools = Toolbox(store, run_id)
    args = {"mode": "upsert", "idempotency_key": "first"}
    assert tools.call("sync_records", args)["error"] == "response_lost"
    assert tools.call("verify_sync", {})["missing_count"] > 0
    assert not tools.call("sync_records", args)["complete"]
    tools.call("sync_records", {"mode": "upsert", "idempotency_key": "remaining"})
    assert tools.call("verify_sync", {})["exact_match"]
    assert verdict(store, run_id)["passed"]


def test_concurrent_same_key_commits_once(store):
    run_id = store.create("partial_sync")
    initial = store.get(run_id)
    args = {"mode": "append", "idempotency_key": "concurrent"}
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: Toolbox(store, run_id).call("sync_records", args), range(6)))
    assert sum(bool(r.get("replayed")) for r in results) == 5
    assert (
        store.get(run_id)["destination_count"] == initial["destination_count"] + initial["source_count"]
    )


def test_receipt_rejects_changed_request(store):
    run_id = store.create("partial_sync")
    tools = Toolbox(store, run_id)
    tools.call("sync_records", {"mode": "upsert", "idempotency_key": "a"})
    before = store.get(run_id)["destination_count"]
    result = tools.call("sync_records", {"mode": "append", "idempotency_key": "a"})
    assert result["error"] == "idempotency_conflict"
    assert store.get(run_id)["destination_count"] == before


def test_readonly_denies_data_and_config_writes_and_requires_ticket(store):
    run_id = store.create("read_only")
    tools = Toolbox(store, run_id)
    for name, args in [
        ("configure_sync", {"key_field": "legacy_id"}),
        ("sync_records", {"mode": "append", "idempotency_key": "a"}),
    ]:
        assert tools.call(name, args)["error"] == "permission_denied"
    assert not verdict(store, run_id, "escalated")["passed"]
    tools.call("escalate", {"reason": "Write access requires an operator."})
    result = verdict(store, run_id, "escalated")
    assert result["passed"] and result["permission_respected"]
    assert not result["resolved"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"mode": "delete", "idempotency_key": "a"},
        {"mode": "upsert"},
        {"mode": "upsert", "idempotency_key": "a", "override_permissions": True},
    ],
)
def test_invalid_arguments_never_mutate(store, arguments):
    run_id = store.create("partial_sync")
    before = store.get(run_id)["destination_count"]
    result = Toolbox(store, run_id).call("sync_records", arguments)
    assert result["error"] == "invalid_arguments"
    assert store.get(run_id)["destination_count"] == before


def test_run_isolation(store):
    one, two = store.create("partial_sync"), store.create("partial_sync")
    before = store.get(two)
    Runner(store).execute(one)
    after = store.get(two)
    assert after["destination_count"] == before["destination_count"]
    assert after["events"] == []


def test_resume_after_committed_write_rebuilds_history(store):
    run_id = store.create("lost_response")
    tools = Toolbox(store, run_id)
    for name in ("inspect_job", "read_runbook", "read_logs"):
        tools.call(name, {})
    tools.call("sync_records", {"mode": "upsert", "idempotency_key": "before-crash"})
    store.update(run_id, status="running", messages=[])
    reopened = Store(store.path)
    reopened.recover_interrupted()
    assert reopened.get(run_id)["status"] == "interrupted"
    run = Runner(reopened).execute(run_id)
    assert run["verdict"]["passed"]
    assert sum(e["name"] == "sync_records" for e in run["events"]) == 1


def test_payload_corruption_is_detected_even_with_matching_counts(store):
    run_id = store.create("corrupt_record")
    tools = Toolbox(store, run_id)
    tools.call("sync_records", {"mode": "upsert", "idempotency_key": "a"})
    with store.connect() as connection:
        row = connection.execute(
            "SELECT * FROM destination WHERE run_id=? LIMIT 1", (run_id,)
        ).fetchone()
        body = json.loads(row["body"])
        body["amount_cents"] += 1
        connection.execute(
            "UPDATE destination SET body=? WHERE row_id=?", (json.dumps(body), row["row_id"])
        )
    result = tools.call("verify_sync", {})
    assert result["source_rows"] == result["destination_rows"]
    assert not result["exact_match"]
    assert result["incorrect_count"] == 1


def test_action_and_trace_rollback_together(store, monkeypatch):
    run_id = store.create("partial_sync")
    initial = store.get(run_id)

    def fail_event(*args, **kwargs):
        raise RuntimeError("simulated disk write failure")

    monkeypatch.setattr(Store, "insert_event", fail_event)
    with pytest.raises(RuntimeError, match="disk write"):
        Toolbox(store, run_id).call("sync_records", {"mode": "upsert", "idempotency_key": "a"})
    final = store.get(run_id)
    assert final["destination_count"] == initial["destination_count"]
    assert final["state"] == initial["state"]
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0
