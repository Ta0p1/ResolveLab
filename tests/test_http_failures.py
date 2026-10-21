from concurrent.futures import ThreadPoolExecutor

from resolvelab.httpdesk.adapter import DeskAdapter
from resolvelab.httpdesk.experiment import episode
from resolvelab.httpdesk.schema import action
from resolvelab.httpdesk.service import DeskServer, DeskState
from resolvelab.policies import PolicyResponseError


def test_concurrent_same_key_commits_exactly_once():
    state = DeskState([], 4103)
    with DeskServer(state) as server:
        adapter = DeskAdapter(server.url)
        try:
            etag = adapter.dispatch(action("get_ticket", ticket_id=state.target))["etag"]
            request = action(
                "patch_ticket",
                ticket_id=state.target,
                etag=etag,
                idempotency_key="concurrent",
                **state.desired,
            )
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda _: adapter.dispatch(request), range(2)))
            assert [r["status"] for r in responses] == [200, 200]
            assert len(state.commits) == 1
        finally:
            adapter.close()


def test_inference_and_protocol_errors_remain_failed_episodes():
    class Broken:
        def next(self, messages):
            raise RuntimeError("model unavailable")

    trace = episode({"id": "probe", "faults": []}, 4101, Broken())
    assert not trace["verdict"]["passed"]
    assert trace["error"] == "inference_error"
    assert not trace["observations"]
    assert len(trace["decisions"]) == 1

    class Malformed:
        def next(self, messages):
            raise PolicyResponseError(
                "invalid",
                {"output_tokens": 192, "json_valid": False, "failure_category": "json_error"},
                2.5,
            )

    trace = episode({"id": "probe", "faults": []}, 4101, Malformed())
    assert trace["error"] == "json_error"
    assert trace["decisions"][0]["usage"]["output_tokens"] == 192
    assert trace["decisions"][0]["seconds"] == 2.5
