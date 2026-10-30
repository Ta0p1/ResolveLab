"""Local models through Ollama's native chat API, with the study's own JSON Schema.

This matches the v0.3 supplementary control: the exact ``action_schema()`` as Ollama's
``format``, temperature 0, a fixed seed and thinking off. Ollama truncates a prompt that
exceeds ``num_ctx`` without an error, so a reply whose prompt filled the window is failed as
``context_limit`` instead of being scored as if the model had seen the whole conversation.
"""

import time

import httpx

from ..httpdesk.schema import action_schema
from .base import fail, parse_action


class OllamaProvider:
    def __init__(
        self,
        model,
        *,
        base_url="http://127.0.0.1:11434",
        num_ctx=8192,
        max_output=192,
        temperature=0.0,
        seed=42,
        think=False,
        keep_alive="10m",
        timeout=300,
        client=None,
    ):
        self.model, self.num_ctx, self.max_output = model, int(num_ctx), int(max_output)
        self.keep_alive = keep_alive
        self.options = {
            "temperature": float(temperature),
            "seed": int(seed),
            "num_ctx": self.num_ctx,
            "num_predict": self.max_output,
        }
        # Options arrive as strings from the CLI; Ollama also accepts levels such as "low".
        flag = str(think).lower()
        self.think = {"true": True, "1": True, "false": False, "0": False}.get(flag, think)
        self.client = client or httpx.Client(base_url=base_url, timeout=float(timeout), trust_env=False)
        self.schema = action_schema()
        self.metadata = {
            "provider": "ollama",
            "model": model,
            "base_url": base_url,
            "protocol": "study JSON Schema via Ollama format",
            "options": self.options,
            "thinking": self.think,
            "retries": 0,
        }
        tags = self.client.get("/api/tags").json().get("models", [])
        match = next((m for m in tags if m["name"] == model), None)
        if match is None:
            raise ValueError(f"Ollama has no model named {model!r}; run `ollama pull {model}`")
        self.metadata["digest"] = match["digest"]
        self.metadata["details"] = match.get("details")

    def next(self, messages):
        start = time.perf_counter()
        response = self.client.post(
            "/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "format": self.schema,
                "options": self.options,
                "think": self.think,
                "keep_alive": self.keep_alive,
                "stream": False,
            },
        )
        response.raise_for_status()
        body = response.json()
        seconds = time.perf_counter() - start
        usage = {
            "input_tokens": body.get("prompt_eval_count", 0),
            "output_tokens": body.get("eval_count", 0),
            "done_reason": body.get("done_reason"),
            "load_duration_ns": body.get("load_duration", 0),
        }
        if usage["input_tokens"] >= self.num_ctx - self.max_output:
            fail(
                "context_limit",
                "Prompt filled the context window; Ollama may have truncated it",
                usage,
                seconds,
            )
        return parse_action(body["message"]["content"].strip(), usage, seconds)
