"""Any OpenAI-compatible chat-completions server: vLLM, SGLang, OpenRouter, Ollama's /v1, OpenAI.

The request asks for a ``json_schema`` response with the portable action schema. Servers
differ in which sampling and token-limit fields they accept, so both are options: set
``temperature=none`` for models that reject it and ``token_field=max_completion_tokens``
where ``max_tokens`` is refused. ``extra`` is a JSON object merged into every request for
server-specific fields, e.g. vLLM's ``{"chat_template_kwargs": {"enable_thinking": false}}``
for Qwen3; it is recorded in the report. The API key is read from an environment variable
named by ``api_key_env`` and is never stored in reports.

For Ollama, prefer the native ``ollama:`` provider: Ollama's /v1 endpoint does not switch
off Qwen3 thinking, which then spends the output budget.
"""

import json
import os
import time

import httpx

from .base import fail, parse_action, portable_schema


class OpenAICompatibleProvider:
    def __init__(
        self,
        model,
        *,
        base_url=None,
        api_key_env="OPENAI_API_KEY",
        max_output=192,
        temperature="0",
        token_field="max_tokens",
        strict=True,
        extra=None,
        timeout=300,
        client=None,
    ):
        self.extra = json.loads(extra) if isinstance(extra, str) else dict(extra or {})
        if not isinstance(self.extra, dict):
            raise ValueError("extra must be a JSON object")
        base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        headers = {}
        key = os.environ.get(api_key_env) if api_key_env else None
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self.model, self.max_output, self.token_field = model, int(max_output), token_field
        self.temperature = None if str(temperature).lower() == "none" else float(temperature)
        self.strict = str(strict).lower() not in {"false", "0", "no"}
        self.client = client or httpx.Client(
            base_url=base_url, headers=headers, timeout=float(timeout), trust_env=False
        )
        self.schema = portable_schema()
        self.metadata = {
            "provider": "openai-compatible",
            "model": model,
            "base_url": base_url,
            "protocol": "portable JSON Schema via response_format",
            "strict": self.strict,
            "temperature": self.temperature,
            "token_field": token_field,
            "max_output_tokens": self.max_output,
            "api_key_env": api_key_env if key else None,
            "extra": self.extra,
            "retries": 0,
        }

    def next(self, messages):
        start = time.perf_counter()
        request = {
            "model": self.model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "tool_action", "strict": self.strict, "schema": self.schema},
            },
            self.token_field: self.max_output,
        }
        if self.temperature is not None:
            request["temperature"] = self.temperature
        request |= self.extra
        response = self.client.post("/chat/completions", json=request)
        response.raise_for_status()
        body = response.json()
        seconds = time.perf_counter() - start
        tokens = body.get("usage") or {}
        usage = {
            "input_tokens": tokens.get("prompt_tokens", 0),
            "output_tokens": tokens.get("completion_tokens", 0),
        }
        choice = body["choices"][0]
        message = choice["message"]
        if message.get("refusal"):
            fail("refusal", f"Model refused: {message['refusal'][:200]}", usage, seconds)
        if choice.get("finish_reason") == "length":
            fail("max_tokens", "Output stopped at the token limit", usage, seconds)
        return parse_action((message.get("content") or "").strip(), usage, seconds)
