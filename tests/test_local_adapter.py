import json

import httpx
import pytest

from resolvelab.policies import OllamaPolicy, PolicyResponseError
from resolvelab.runner import Runner
from resolvelab.store import Store


def test_native_tool_protocol_and_returned_index(monkeypatch):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "tool_calls": [{"function": {"index": 0, "name": "inspect_job", "arguments": {}}}]
                },
                "prompt_eval_count": 80,
                "eval_count": 25,
                "done_reason": "stop",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr("resolvelab.policies.httpx.Client", lambda **_: client)
    provider = OllamaPolicy("test")
    messages = provider.initial_messages()
    provider.append_observation(messages, "read_logs", {}, {"untrusted": True, "logs": ["diagnostic"]})
    action, usage, seconds = provider.next(messages)
    assert action.name == "inspect_job"
    assert usage == {"input_tokens": 80, "output_tokens": 25}
    assert seconds >= 0
    assert requests[0]["messages"][-1]["role"] == "tool"
    assert requests[0]["messages"][-1]["tool_name"] == "read_logs"
    assert requests[0]["tools"][0]["type"] == "function"
    assert "format" not in requests[0]
    assert requests[0]["options"]["num_predict"] == 2048


@pytest.mark.parametrize(
    "calls",
    [
        [],
        [
            {"function": {"name": "inspect_job", "arguments": {}}},
            {"function": {"name": "sync_records", "arguments": {}}},
        ],
    ],
)
def test_non_single_tool_response_is_rejected(monkeypatch, calls):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "message": {"tool_calls": calls},
                    "prompt_eval_count": 40,
                    "eval_count": 60,
                    "done_reason": "length",
                },
            )
        )
    )
    monkeypatch.setattr("resolvelab.policies.httpx.Client", lambda **_: client)
    with pytest.raises(PolicyResponseError) as caught:
        OllamaPolicy("test").next([])
    assert caught.value.usage["output_tokens"] == (60 if calls else 120)


def test_truncation_retry_is_bounded_accounted_and_does_not_mutate_history(monkeypatch):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "tool_calls": []
                    if len(requests) == 1
                    else [{"function": {"name": "verify_sync", "arguments": {}}}]
                },
                "done_reason": "length" if len(requests) == 1 else "stop",
                "prompt_eval_count": 100,
                "eval_count": 2048 if len(requests) == 1 else 25,
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr("resolvelab.policies.httpx.Client", lambda **_: client)
    messages = OllamaPolicy("test").initial_messages()
    before = json.dumps(messages)
    action, usage, _ = OllamaPolicy("test").next(messages)
    assert action.name == "verify_sync"
    assert usage["input_tokens"] == 200 and usage["output_tokens"] == 2073
    assert len(usage["attempts"]) == 2
    assert requests[1]["options"]["num_predict"] == 4096
    assert json.dumps(messages) == before


def test_invalid_model_response_records_usage_as_failure(tmp_path, monkeypatch):
    def invalid(*_):
        raise PolicyResponseError("No tool call", {"input_tokens": 40, "output_tokens": 60}, 0.1)

    monkeypatch.setattr(OllamaPolicy, "next", invalid)
    store = Store(tmp_path / "test.sqlite")
    run = Runner(store).execute(store.create("partial_sync", policy="ollama"))
    assert run["status"] == "error"
    assert not run["verdict"]["passed"]
    assert run["input_tokens"] == 40
    assert run["output_tokens"] == 60
    assert run["events"][-1]["name"] == "invalid_response"


def test_retry_transport_failure_retains_first_attempt_usage(monkeypatch):
    attempts = []

    def handle(request):
        attempts.append(request)
        if len(attempts) == 2:
            raise httpx.ReadTimeout("retry timed out", request=request)
        return httpx.Response(
            200,
            json={"message": {}, "done_reason": "length", "prompt_eval_count": 40, "eval_count": 2048},
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr("resolvelab.policies.httpx.Client", lambda **_: client)
    with pytest.raises(PolicyResponseError) as caught:
        OllamaPolicy("test").next([])
    assert caught.value.usage["output_tokens"] == 2048
    assert len(attempts) == 2
