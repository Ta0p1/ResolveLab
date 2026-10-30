"""Model providers and the casedesk CLI, without network access or model weights.

Fake servers replay the scripted teacher's actions, so a correct provider must carry an
episode to a pass through the real HTTP environment and the real grader.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from resolvelab.casedesk import cli
from resolvelab.casedesk.manifest import load_manifest
from resolvelab.casedesk.runner import actions_of, run_episode
from resolvelab.httpdesk.schema import ARGUMENTS, action_json, action_schema
from resolvelab.providers import make_provider, parse_spec
from resolvelab.providers.anthropic import AnthropicProvider
from resolvelab.providers.base import portable_schema
from resolvelab.providers.ollama import OllamaProvider
from resolvelab.providers.openai_compat import OpenAICompatibleProvider

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = load_manifest(ROOT / "benchmarks/casedesk-v2.json")
SPEC = next(s for s in MANIFEST["episodes"]["test"] if s["id"] == "test-test_conflict_rate-07")


def teacher_texts(spec=SPEC):
    return [action_json(a) for a in actions_of(run_episode(spec))]


def test_portable_schema_is_an_object_that_covers_every_tool():
    schema = portable_schema()
    assert schema["type"] == "object" and schema["required"] == ["name", "arguments"]
    assert schema["properties"]["name"]["enum"] == list(ARGUMENTS)
    assert len(schema["properties"]["arguments"]["anyOf"]) == len(ARGUMENTS)
    text = json.dumps(schema)
    assert '"title"' not in text and "maximum" not in text and "minimum" not in text
    for action in actions_of(run_episode(SPEC)):
        branch = schema["properties"]["arguments"]["anyOf"][list(ARGUMENTS).index(action["name"])]
        assert set(action["arguments"]) == set(branch["required"])


def ollama_transport(texts, requests, prompt_tokens=900):
    replies = iter(texts)

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "qwen3:4b", "digest": "abc", "details": {}}]}
            )
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"content": next(replies)},
                "prompt_eval_count": prompt_tokens,
                "eval_count": 40,
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ollama")


def test_ollama_provider_runs_a_passing_episode_with_the_study_schema():
    requests = []
    provider = OllamaProvider(
        "qwen3:4b", think="false", client=ollama_transport(teacher_texts(), requests)
    )
    trace = run_episode(SPEC, provider)
    assert trace["verdict"]["passed"]
    assert requests[0]["format"] == action_schema()
    assert requests[0]["think"] is False and requests[0]["options"]["temperature"] == 0.0
    assert requests[0]["keep_alive"] == "10m"
    assert requests[0]["messages"][0]["role"] == "system"
    assert provider.metadata["digest"] == "abc"
    assert trace["decisions"][0]["usage"]["input_tokens"] == 900


def test_ollama_flags_a_prompt_that_filled_the_context_window():
    provider = OllamaProvider(
        "qwen3:4b", client=ollama_transport(teacher_texts(), [], prompt_tokens=8100)
    )
    trace = run_episode(SPEC, provider)
    assert trace["error"] == "context_limit" and not trace["verdict"]["passed"]


def test_ollama_invalid_output_ends_the_episode_without_repair():
    provider = OllamaProvider("qwen3:4b", client=ollama_transport(['{"name": "list_tickets"'], []))
    trace = run_episode(SPEC, provider)
    assert trace["error"] == "json_error" and not trace["observations"]


def test_ollama_requires_the_model_to_be_installed():
    with pytest.raises(ValueError, match="ollama pull"):
        OllamaProvider("missing:1b", client=ollama_transport([], []))


def openai_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://server/v1")


def test_openai_compatible_provider_runs_a_passing_episode(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-secret-value")
    replies, requests, headers = iter(teacher_texts()), [], []

    def handler(request):
        requests.append(json.loads(request.content))
        headers.append(request.headers.get("authorization"))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": next(replies)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 30},
            },
        )

    # The key is sent by the client the provider builds; here the test client stands in for it.
    provider = OpenAICompatibleProvider(
        "local-model", api_key_env="TEST_KEY", client=openai_client(handler)
    )
    trace = run_episode(SPEC, provider)
    assert trace["verdict"]["passed"]
    body = requests[0]
    assert body["response_format"]["json_schema"]["schema"] == portable_schema()
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["temperature"] == 0.0 and body["max_tokens"] == 192
    assert "sk-secret-value" not in json.dumps(provider.metadata)
    assert provider.metadata["api_key_env"] == "TEST_KEY"


def test_openai_compatible_sends_the_key_from_the_named_variable(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-secret-value")
    provider = OpenAICompatibleProvider("m", api_key_env="TEST_KEY", base_url="http://server/v1")
    assert provider.client.headers["authorization"] == "Bearer sk-secret-value"
    provider.client.close()


@pytest.mark.parametrize("options", [{"temperature": "none"}, {"token_field": "max_completion_tokens"}])
def test_openai_compatible_sampling_and_token_options(options):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": teacher_texts()[0]}}]})

    provider = OpenAICompatibleProvider("m", client=openai_client(handler), **options)
    provider.next([{"role": "user", "content": "x"}])
    if options.get("temperature") == "none":
        assert "temperature" not in requests[0]
    else:
        assert requests[0]["max_completion_tokens"] == 192 and "max_tokens" not in requests[0]


@pytest.mark.parametrize(
    "reply,error",
    [
        (
            httpx.Response(200, json={"choices": [{"message": {"content": None, "refusal": "no"}}]}),
            "refusal",
        ),
        (
            httpx.Response(
                200, json={"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]}
            ),
            "max_tokens",
        ),
        (httpx.Response(500, json={"error": "down"}), "inference_error"),
    ],
)
def test_openai_compatible_failures_are_recorded_not_retried(reply, error):
    provider = OpenAICompatibleProvider("m", client=openai_client(lambda request: reply))
    trace = run_episode(SPEC, provider)
    assert trace["error"] == error and not trace["observations"]


class FakeMessages:
    def __init__(self, texts, stop_reason="end_turn"):
        self.texts, self.calls, self.stop_reason = iter(texts), [], stop_reason

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = [
            SimpleNamespace(type="thinking", thinking="", signature="sig"),
            SimpleNamespace(type="text", text=next(self.texts)),
        ]
        usage = SimpleNamespace(
            input_tokens=1200,
            output_tokens=80,
            cache_read_input_tokens=1000,
            cache_creation_input_tokens=0,
        )
        return SimpleNamespace(
            content=content,
            stop_reason=self.stop_reason,
            usage=usage,
            stop_details=SimpleNamespace(category="cyber"),
        )


def test_anthropic_provider_uses_structured_outputs_and_replays_its_own_turns():
    fake = FakeMessages(teacher_texts())
    provider = AnthropicProvider("claude-opus-5-5", client=SimpleNamespace(messages=fake))
    trace = run_episode(SPEC, provider)
    assert trace["verdict"]["passed"]
    first, later = fake.calls[0], fake.calls[3]
    assert first["system"].startswith("You operate CaseDesk")
    assert all(m["role"] != "system" for m in first["messages"])
    assert first["output_config"] == {
        "format": {"type": "json_schema", "schema": portable_schema()},
        "effort": "high",
    }
    assert first["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in first and "thinking" not in first
    model_turns = [m["content"] for m in later["messages"] if not isinstance(m["content"], str)]
    assert len(model_turns) == 3 and all(turn[0].type == "thinking" for turn in model_turns)
    assert trace["decisions"][0]["usage"]["cache_read_input_tokens"] == 1000


def test_anthropic_provider_starts_each_episode_with_a_clean_history():
    other = MANIFEST["episodes"]["test"][0]
    fake = FakeMessages(teacher_texts() + teacher_texts(other))
    provider = AnthropicProvider("claude-opus-5-5", client=SimpleNamespace(messages=fake))
    assert run_episode(SPEC, provider)["verdict"]["passed"]
    calls_before = len(fake.calls)
    assert run_episode(other, provider)["verdict"]["passed"]
    first_of_second = fake.calls[calls_before]["messages"]
    assert all(isinstance(m["content"], str) for m in first_of_second)


def test_anthropic_refusal_is_a_failure_not_a_fallback():
    fake = FakeMessages(teacher_texts(), stop_reason="refusal")
    provider = AnthropicProvider("claude-opus-5-5", client=SimpleNamespace(messages=fake))
    trace = run_episode(SPEC, provider)
    assert trace["error"] == "refusal" and provider.metadata["refusal_fallbacks"] is False


def test_openai_compatible_merges_server_specific_fields():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": teacher_texts()[0]}}]})

    extra = '{"chat_template_kwargs": {"enable_thinking": false}}'
    provider = OpenAICompatibleProvider("m", extra=extra, client=openai_client(handler))
    provider.next([{"role": "user", "content": "x"}])
    assert requests[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert provider.metadata["extra"] == {"chat_template_kwargs": {"enable_thinking": False}}
    with pytest.raises(ValueError):
        OpenAICompatibleProvider("m", extra="[1]", client=openai_client(handler))


def test_hf_spec_pins_the_study_revision_and_passes_the_adapter(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "resolvelab.casedesk.policy.make_policy",
        lambda arm, adapter: calls.append((arm, adapter)) or "policy",
    )
    policy, arm = make_provider("hf:Qwen/Qwen3-0.6B", {"adapter": "runs/dagger-42/epoch-3"})
    study = json.loads((ROOT / "benchmarks/casedesk-v2-study.json").read_text(encoding="utf-8"))
    assert policy == "policy" and calls[0][1] == "runs/dagger-42/epoch-3"
    assert arm["revision"] == study["models"]["qwen3-0.6b"]["revision"]
    assert arm["max_output"] == 192 and arm["context"] == 8192
    _, thinking = make_provider("hf:Qwen/Qwen3-1.7B@abc", {"thinking": "512"})
    assert thinking["revision"] == "abc" and thinking["thinking_budget"] == 512


def test_model_specs():
    assert parse_spec("ollama:qwen3:4b") == ("ollama", "qwen3:4b")
    assert parse_spec("hf:Qwen/Qwen3-0.6B@abc") == ("hf", "Qwen/Qwen3-0.6B@abc")
    for bad in ("gpt", "ollama:", "vllm:x"):
        with pytest.raises(ValueError):
            parse_spec(bad)
    assert make_provider("teacher")[0] is None
    with pytest.raises(ValueError):
        make_provider("teacher", {"effort": "high"})


def test_cli_lists_runs_and_evaluates(tmp_path, capsys):
    assert cli.main(["episodes", "--pool", "dev"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 40
    assert cli.main(["run", "--episode", SPEC["id"]]) == 0
    assert "grader: PASS" in capsys.readouterr().out
    output = tmp_path / "teacher-dev.json"
    assert (
        cli.main(
            ["eval", "--pool", "dev", "--model", "teacher", "--output", str(output), "--limit", "2"]
        )
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "completed" and report["summary"]["passed"] == 2
    assert report["arm"]["provider"] == "teacher"


def test_console_entry_point_dispatches_casedesk(monkeypatch, capsys):
    from resolvelab import main

    monkeypatch.setattr("sys.argv", ["resolvelab", "casedesk", "episodes", "--pool", "dev"])
    with pytest.raises(SystemExit) as stop:
        main.main()
    assert stop.value.code == 0 and "dev-" in capsys.readouterr().out
