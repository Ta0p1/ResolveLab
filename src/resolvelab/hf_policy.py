"""Optional local Transformers policy. Identical prompt/decoder before and after SFT."""

import json
import re
import time

from .policies import SYSTEM_PROMPT, Decision, PolicyResponseError
from .scenarios import TASK
from .store import dumps
from .tools import tool_catalog


def initial_messages():
    instructions = SYSTEM_PROMPT.replace(
        "Use the supplied function calls, not JSON in ordinary text.",
        'Return ONLY a JSON object with keys "name" and "arguments", with no markdown fences.',
    )
    return [
        {"role": "system", "content": instructions + "\nAvailable tools:\n" + dumps(tool_catalog())},
        {"role": "user", "content": TASK},
    ]


def append_observation(messages, name, arguments, result):
    messages.extend(
        [
            {"role": "assistant", "content": dumps({"name": name, "arguments": arguments})},
            {"role": "user", "content": dumps({"tool": name, "result": result})},
        ]
    )


def prompt_ids(tokenizer, messages):
    return tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    )


def parse_action(content, allow_json_fences=False):
    if allow_json_fences:
        match = re.fullmatch(r"```(?:json)?\s*\n([\s\S]*?)\n```", content.strip())
        if match:
            content = match.group(1)
    return Decision.model_validate(json.loads(content))


class HFPolicy:
    initial_messages = staticmethod(initial_messages)
    append_observation = staticmethod(append_observation)

    def __init__(
        self, base, revision, adapter=None, max_output=192, context=4096, allow_json_fences=False
    ):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU required for this local experiment")
        self.tokenizer = AutoTokenizer.from_pretrained(base, revision=revision)
        self.model = AutoModelForCausalLM.from_pretrained(
            base,
            revision=revision,
            torch_dtype=torch.bfloat16,
            attn_implementation="sdpa",
        ).to("cuda")
        if adapter:
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(self.model, adapter)
        self.model.eval()
        self.max_output, self.context = max_output, context
        self.allow_json_fences = allow_json_fences
        self.metadata = {
            "base": base,
            "revision": revision,
            "adapter": bool(adapter),
            "max_output_tokens": max_output,
            "context_tokens": context,
            "thinking": False,
            "do_sample": False,
            "protocol": "json_action_v1+outer_fence" if allow_json_fences else "json_action_v1",
            "dtype": "bfloat16",
            "attention": "sdpa",
            "retries": 0,
            "prompt_sha256": __import__("hashlib")
            .sha256(dumps(initial_messages()).encode())
            .hexdigest(),
        }

    def next(self, messages):
        import torch

        start = time.perf_counter()
        ids = prompt_ids(self.tokenizer, messages)
        if len(ids) + self.max_output > self.context:
            raise PolicyResponseError(
                "Context budget exceeded; no silent truncation",
                {"input_tokens": 0, "output_tokens": 0},
                0,
            )
        inputs = torch.tensor([ids], device="cuda")
        with torch.inference_mode():
            output = self.model.generate(
                input_ids=inputs,
                attention_mask=torch.ones_like(inputs),
                max_new_tokens=self.max_output,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        generated = output[0, len(ids) :]
        content = self.tokenizer.decode(generated, skip_special_tokens=True).strip()
        usage = {"input_tokens": len(ids), "output_tokens": len(generated)}
        seconds = time.perf_counter() - start
        try:
            action = parse_action(content, self.allow_json_fences)
        except (ValueError, TypeError) as exc:
            raise PolicyResponseError(f"Invalid JSON action: {content[:300]}", usage, seconds) from exc
        if self.allow_json_fences and content.startswith("```"):
            usage["outer_fence_removed"] = True
        return action, usage, seconds
