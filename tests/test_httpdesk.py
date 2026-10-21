"""Contract and outcome tests through actual HTTP sockets, not ASGI test clients."""

import copy
from pathlib import Path

import httpx
import pytest

from resolvelab.httpdesk.adapter import DeskAdapter
from resolvelab.httpdesk.benchmark import cases, load_manifest, validate_rows
from resolvelab.httpdesk.experiment import episode
from resolvelab.httpdesk.grading import grade
from resolvelab.httpdesk.schema import action, action_schema, validate_action
from resolvelab.httpdesk.service import DeskServer, DeskState

MANIFEST = Path(__file__).resolve().parents[1] / "benchmarks/httpdesk-v1.json"


@pytest.fixture
def desk():
    state = DeskState([], 6301)
    with DeskServer(state) as server:
        adapter = DeskAdapter(server.url)
        yield state, adapter
        adapter.close()


def get(state, adapter):
    return adapter.dispatch(action("get_ticket", ticket_id=state.target))


def patch(state, adapter, etag, key="op-1", **changes):
    return adapter.dispatch(
        action(
            "patch_ticket",
            ticket_id=state.target,
            etag=etag,
            idempotency_key=key,
            **(state.desired | changes),
        )
    )


def test_pagination_and_exact_reference(desk):
    state, adapter = desk
    cursor, found = "", []
    while True:
        result = adapter.dispatch(action("list_tickets", cursor=cursor))
        assert result["status"] == 200
        assert len(result["body"]["tickets"]) <= 2
        found.extend(result["body"]["tickets"])
        cursor = result["body"]["next_cursor"]
        if not cursor:
            break
    assert len(found) == len(state.tickets)
    assert [t["id"] for t in found if t["external_ref"] == state.reference] == [state.target]
    assert adapter.dispatch(action("list_tickets", cursor="invented"))["status"] == 400


def test_lost_ack_idempotency_and_no_hidden_retry(desk):
    state, adapter = desk
    state.faults.add("lost_ack")
    etag = get(state, adapter)["etag"]
    assert patch(state, adapter, etag)["status"] == 502
    assert len(state.commits) == 1
    assert len(adapter.requests) == 2
    assert patch(state, adapter, etag)["status"] == 200
    assert len(state.commits) == 1
    wrong = "low" if state.desired["priority"] != "low" else "high"
    assert patch(state, adapter, etag, priority=wrong)["status"] == 409
    assert grade(state, "resolved")["passed"] is False
    get(state, adapter)
    assert grade(state, "resolved")["passed"] is True


def test_etag_refresh_preserves_concurrent_operator(desk):
    state, adapter = desk
    state.faults.add("conflict")
    etag = get(state, adapter)["etag"]
    assert patch(state, adapter, etag)["status"] == 412
    assert patch(state, adapter, etag)["status"] == 412
    assert not state.commits
    latest = get(state, adapter)
    assert latest["etag"] != etag
    assert latest["body"]["assignee"] == "concurrent-operator"
    assert patch(state, adapter, latest["etag"])["status"] == 200
    get(state, adapter)
    assert grade(state, "resolved")["passed"]


def test_retry_after_and_mid_task_permission_revocation(desk):
    state, adapter = desk
    state.faults.update({"rate_limit", "revoke"})
    before = get(state, adapter)
    assert before["body"]["write_allowed"]
    assert patch(state, adapter, before["etag"])["status"] == 429
    adapter.dispatch(action("wait", seconds=2))
    assert patch(state, adapter, before["etag"])["retry_after"] == "1"
    adapter.dispatch(action("wait", seconds=1))
    assert patch(state, adapter, before["etag"])["status"] == 403
    assert not get(state, adapter)["body"]["write_allowed"]
    assert not grade(state, "escalated")["passed"]
    adapter.dispatch(action("escalate", reason="Permission revoked"))
    assert grade(state, "escalated")["passed"]
    assert not state.commits


def test_false_claim_and_unnecessary_write_fail(desk):
    state, adapter = desk
    assert grade(state, "resolved")["false_success"]
    etag = get(state, adapter)["etag"]
    patch(state, adapter, etag)
    assert not grade(state, "resolved")["passed"]
    etag = get(state, adapter)["etag"]
    assert grade(state, "resolved")["passed"]
    patch(state, adapter, etag, key="new-op")
    get(state, adapter)
    verdict = grade(state, "resolved")
    assert not verdict["passed"] and verdict["redundant_commits"] == 1


def test_wrong_record_mutation_cannot_be_hidden_by_final_state(desk):
    state, adapter = desk
    other = next(k for k in state.tickets if k != state.target)
    snapshot = copy.deepcopy(state.tickets[other])
    read = adapter.dispatch(action("get_ticket", ticket_id=other))
    adapter.dispatch(
        action(
            "patch_ticket", ticket_id=other, etag=read["etag"], idempotency_key="bad", **state.desired
        )
    )
    # Even restoring the payload cannot erase the historical unsafe mutation.
    state.tickets[other] = snapshot
    patch(state, adapter, get(state, adapter)["etag"], key="correct")
    get(state, adapter)
    assert grade(state, "resolved")["unsafe_mutations"] == 1
    assert not grade(state, "resolved")["passed"]


def test_transport_error_is_observed_without_retry(desk, monkeypatch):
    state, adapter = desk
    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr(adapter.client, "request", fail)
    result = get(state, adapter)
    assert result == {"status": 0, "error": "ReadTimeout", "commit_state": "unknown"}
    assert len(calls) == 1
    assert not state.http_events


@pytest.mark.parametrize("template,seed", list(cases(load_manifest(MANIFEST), "test")))
def test_scripted_oracle_validates_frozen_environment(template, seed):
    trace = episode(template, seed)
    assert trace["verdict"]["passed"], trace["verdict"]
    assert len(trace["http_client"]) == len(trace["http_server"])
    assert all("http" not in t["id"] for t in trace["final_state"].values())


def test_runtime_schema_rejects_tool_argument_mismatch():
    with pytest.raises(ValueError):
        validate_action({"name": "get_ticket", "arguments": {"cursor": ""}})
    with pytest.raises(ValueError):
        action("wait", seconds=True)
    assert len(action_schema()["anyOf"]) == 6


def test_test_split_is_rejected_for_sft():
    with pytest.raises(ValueError, match="Test data"):
        validate_rows([], load_manifest(MANIFEST), "test")
