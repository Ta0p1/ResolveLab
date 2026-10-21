import importlib.util
import json
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from resolvelab.policies import PolicyResponseError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "http_ollama_control", ROOT / "scripts/http_ollama_control.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ROOT / "benchmarks/httpdesk-ollama-control.json").read_text(encoding="utf-8"))


class Tokenizer:
    def apply_chat_template(self, messages, **kwargs):
        return [1, 2, 3]


def make_policy(content):
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": CONFIG["model"],
                            "digest": CONFIG["digest"],
                            "details": {"quantization_level": "Q4_K_M"},
                        }
                    ]
                },
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        if request.url.path == "/api/show":
            return httpx.Response(
                200, json={"template": "test", "parameters": "", "capabilities": ["completion"]}
            )
        return httpx.Response(
            200,
            json={
                "message": {"content": content},
                "prompt_eval_count": 2000,
                "eval_count": 192,
                "done_reason": "length",
                "load_duration": 10,
            },
        )

    client = httpx.Client(base_url="http://localhost:11434", transport=httpx.MockTransport(respond))
    return module.OllamaSchemaPolicy(CONFIG, client, Tokenizer()), requests


def test_control_uses_static_schema_without_retry_and_retains_failed_usage():
    policy, requests = make_policy("invalid JSON")
    with closing(policy.client), pytest.raises(PolicyResponseError) as error:
        policy.next([{"role": "user", "content": "task"}])
    posts = [r for r in requests if r.url.path == "/api/chat"]
    assert len(posts) == 1
    body = json.loads(posts[0].content)
    assert body["think"] is False
    assert body["options"]["num_predict"] == 192
    assert len(body["format"]["anyOf"]) == 6
    assert error.value.usage["output_tokens"] == 192
    assert error.value.usage["done_reason"] == "length"
    assert error.value.usage["json_valid"] is False


def test_control_validates_schema_and_preserves_backend_counts():
    policy, requests = make_policy('{"name":"finish","arguments":{"outcome":"resolved"}}')
    with closing(policy.client):
        result, usage, _ = policy.next([])
    assert result.name == "finish"
    assert usage["schema_valid"] is True
    assert usage["context_guard_tokens"] == 3
    assert usage["input_tokens"] == 2000
    assert usage["load_duration_ns"] == 10
    assert len([r for r in requests if r.url.path == "/api/chat"]) == 1
