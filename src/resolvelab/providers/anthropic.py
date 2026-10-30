"""Claude through the official Anthropic SDK (``pip install "resolvelab[anthropic]"``).

- The action comes back through structured outputs (``output_config.format``) with the
  portable schema; forced ``tool_choice`` is rejected by current models.
- No sampling parameters (current models reject them). Thinking is left at the model's
  default (adaptive, and not switchable off, on Claude Opus 5.5); ``effort`` is set
  explicitly and recorded, because it changes both quality and cost.
- Refusal fallbacks are deliberately not enabled: a fallback would hand the episode to a
  different model mid-run and the score would no longer describe the model under test. A
  refusal ends the episode as a failure with category ``refusal``.
- The harness transcript stores each action as JSON text. To keep the conversation
  append-only, as preserved thinking requires, this provider sends back its own earlier
  responses' content blocks unchanged in place of those texts.
- The system prompt and demonstration are a stable prefix, so automatic prompt caching is on.

Credentials resolve the SDK's way: ``ANTHROPIC_API_KEY``, ``ANTHROPIC_AUTH_TOKEN`` or an
``ant auth login`` profile.
"""

import time

from .base import fail, parse_action, portable_schema, split_system


class AnthropicProvider:
    def __init__(self, model="claude-opus-5-5", *, effort="high", max_tokens=16000, client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client, self.model, self.max_tokens = client, model, int(max_tokens)
        self.effort = None if str(effort).lower() == "none" else effort
        self.schema = portable_schema()
        self.turns, self.last, self.static = [], None, 0
        self.metadata = {
            "provider": "anthropic",
            "model": model,
            "protocol": "portable JSON Schema via output_config.format",
            "effort": self.effort,
            "thinking": "model default",
            "max_tokens": self.max_tokens,
            "refusal_fallbacks": False,
            "prompt_caching": "automatic",
            "retries": "SDK default for 408/409/429/5xx and connection errors",
        }

    def _conversation(self, messages):
        """API messages with this episode's earlier model turns replayed verbatim."""
        continuing = (
            self.last is not None
            and len(messages) == len(self.last) + 2
            and messages[: len(self.last)] == self.last
        )
        if not continuing:
            self.turns, self.static = [], len(messages)
        self.last = [dict(m) for m in messages]
        system, rest = split_system(messages[: self.static])
        for k, turn in enumerate(self.turns):
            rest.append({"role": "assistant", "content": turn})
            rest.append(messages[self.static + 2 * k + 1])
        return system, rest

    def next(self, messages):
        start = time.perf_counter()
        system, conversation = self._conversation(messages)
        output_config = {"format": {"type": "json_schema", "schema": self.schema}}
        if self.effort:
            output_config["effort"] = self.effort
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=conversation,
            output_config=output_config,
            cache_control={"type": "ephemeral"},
        )
        seconds = time.perf_counter() - start
        tokens = response.usage
        usage = {
            "input_tokens": tokens.input_tokens,
            "output_tokens": tokens.output_tokens,
            "cache_read_input_tokens": getattr(tokens, "cache_read_input_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(tokens, "cache_creation_input_tokens", 0) or 0,
            "stop_reason": response.stop_reason,
        }
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            fail("refusal", f"Model declined (category: {category})", usage, seconds)
        if response.stop_reason == "max_tokens":
            fail("max_tokens", "Response stopped at max_tokens", usage, seconds)
        text = next((block.text for block in response.content if block.type == "text"), "")
        result = parse_action(text.strip(), usage, seconds)
        self.turns.append(response.content)
        return result
