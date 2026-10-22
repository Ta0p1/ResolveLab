"""Decoding variants on the frozen v0.3 StructuredPolicy.

Greedy non-thinking arms use ``StructuredPolicy`` unchanged, so their decoding is identical to
v0.3. This subclass adds two things the v2 study needs and nothing else:

- seeded sampling, used only to diversify learner rollouts for DAgger state collection;
- Qwen3 thinking mode for a stronger baseline: free-form reasoning up to a token budget, then
  the same static JSON-Schema constrained action. Reasoning is not kept in later turns,
  matching the Qwen3 chat template's own multi-turn behaviour.
"""

import json
import time

from ..httpdesk.policy import StructuredPolicy
from ..httpdesk.schema import validate_action
from ..policies import PolicyResponseError

THINK_END = "</think>"


QWEN3_THINKING_SAMPLING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20}


class ConstrainedPolicy(StructuredPolicy):
    def __init__(
        self, config, adapter=None, *, temperature=None, seed=0, thinking_budget=0, think_sampling=None
    ):
        super().__init__(config, adapter)
        self.temperature, self.seed, self.thinking_budget = temperature, seed, thinking_budget
        self.think_sampling = think_sampling
        self.calls = 0
        self.think_end = self.tokenizer.convert_tokens_to_ids(THINK_END)
        self.metadata.update(
            {
                "thinking": bool(thinking_budget),
                "thinking_budget_tokens": thinking_budget,
                "thinking_sampling": think_sampling,
                "do_sample": temperature is not None,
                "temperature": temperature,
                "sampling_seed": seed if temperature is not None or think_sampling else None,
            }
        )

    def generate(self, ids, max_new_tokens, constraint=None, stop=None, sampling=None):
        import torch

        inputs = torch.tensor([ids], device="cuda")
        options = {"do_sample": False}
        if sampling:
            torch.manual_seed(self.seed * 1_000_003 + self.calls)
            options = {"do_sample": True, **sampling}
        with torch.inference_mode():
            output = self.model.generate(
                input_ids=inputs,
                attention_mask=torch.ones_like(inputs),
                max_new_tokens=max_new_tokens,
                pad_token_id=self.tokenizer.eos_token_id,
                eos_token_id=stop or self.tokenizer.eos_token_id,
                prefix_allowed_tokens_fn=constraint,
                **options,
            )
        return output[0, len(ids) :].tolist()

    def next(self, messages):
        from lmformatenforcer import CharacterLevelParserConfig, JsonSchemaParser
        from lmformatenforcer.integrations.transformers import (
            build_transformers_prefix_allowed_tokens_fn,
        )

        start = time.perf_counter()
        self.calls += 1
        ids = self.tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=bool(self.thinking_budget),
        )
        budget = self.thinking_budget + self.max_output
        if len(ids) + budget > self.context:
            raise PolicyResponseError(
                "Context budget exceeded",
                {"input_tokens": 0, "output_tokens": 0, "failure_category": "context_limit"},
                0,
            )
        thought = []
        if self.thinking_budget:
            eos = self.tokenizer.eos_token_id
            thought = self.generate(
                ids, self.thinking_budget, stop=[self.think_end, eos], sampling=self.think_sampling
            )
            if thought and thought[-1] == self.think_end:
                closing = "\n\n"
            else:
                # Budget exhausted (or a stray end-of-turn): close the thought, as Qwen3's
                # documented budget control does, then decode the action.
                thought = thought[:-1] if thought and thought[-1] == eos else thought
                closing = "\n</think>\n\n"
            thought += self.tokenizer.encode(closing, add_special_tokens=False)
        constraint = build_transformers_prefix_allowed_tokens_fn(
            self.tokenizer_data,
            JsonSchemaParser(
                self.schema, config=CharacterLevelParserConfig(force_json_field_order=True)
            ),
        )
        sampling = None
        if self.temperature is not None:
            sampling = {"temperature": self.temperature, "top_p": 1.0, "top_k": 0}
        generated = self.generate(ids + thought, self.max_output, constraint, sampling=sampling)
        content = self.tokenizer.decode(generated, skip_special_tokens=True).strip()
        usage = {
            "input_tokens": len(ids),
            "thinking_tokens": len(thought),
            "output_tokens": len(generated) + len(thought),
            "raw_output": content,
            "json_valid": False,
            "schema_valid": False,
        }
        seconds = time.perf_counter() - start
        try:
            value = json.loads(content)
            usage["json_valid"] = True
            decision = validate_action(value)
            usage["schema_valid"] = True
        except (ValueError, TypeError) as exc:
            usage["failure_category"] = "schema_error" if usage["json_valid"] else "json_error"
            raise PolicyResponseError(str(exc)[:300], usage, seconds) from exc
        return decision, usage, seconds


def make_policy(arm, adapter=None):
    """Greedy non-thinking arms get the untouched v0.3 decoder; others the subclass."""
    if arm.get("temperature") is None and not arm.get("thinking_budget"):
        return StructuredPolicy(arm, adapter)
    return ConstrainedPolicy(
        arm,
        adapter,
        temperature=arm.get("temperature"),
        seed=arm.get("sampling_seed", 0),
        thinking_budget=arm.get("thinking_budget", 0),
        think_sampling=QWEN3_THINKING_SAMPLING if arm.get("thinking_budget") else None,
    )
