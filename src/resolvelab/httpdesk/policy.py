"""Full tool-schema constrained generation, with no observation-dependent constraints."""

import importlib.metadata
import json
import time

from ..benchmark import digest
from ..hf_policy import HFPolicy, prompt_ids
from ..policies import PolicyResponseError
from .schema import action_schema, initial_messages, validate_action


class StructuredPolicy(HFPolicy):
    def __init__(self, config, adapter=None):
        super().__init__(
            config["base"], config["revision"], adapter, config["max_output"], config["context"]
        )
        from lmformatenforcer.integrations.transformers import build_token_enforcer_tokenizer_data

        self.schema = action_schema()
        self.tokenizer_data = build_token_enforcer_tokenizer_data(self.tokenizer)
        self.metadata.update(
            {
                "protocol": "httpdesk_json_schema_v1",
                "schema_sha256": digest(self.schema),
                "prompt_sha256": digest(initial_messages("TASK_PLACEHOLDER")),
                "decoder": "lm-format-enforcer",
                "decoder_version": importlib.metadata.version("lm-format-enforcer"),
                "state_dependent_constraints": False,
                "force_json_field_order": True,
                "dependencies": {
                    p: importlib.metadata.version(p)
                    for p in ("torch", "transformers", "peft", "lm-format-enforcer")
                },
                "hardware": __import__("torch").cuda.get_device_name(0),
            }
        )

    def next(self, messages):
        import torch
        from lmformatenforcer import CharacterLevelParserConfig, JsonSchemaParser
        from lmformatenforcer.integrations.transformers import (
            build_transformers_prefix_allowed_tokens_fn,
        )

        start = time.perf_counter()
        ids = prompt_ids(self.tokenizer, messages)
        if len(ids) + self.max_output > self.context:
            raise PolicyResponseError(
                "Context budget exceeded",
                {"input_tokens": 0, "output_tokens": 0, "failure_category": "context_limit"},
                0,
            )
        constraint = build_transformers_prefix_allowed_tokens_fn(
            self.tokenizer_data,
            JsonSchemaParser(
                self.schema, config=CharacterLevelParserConfig(force_json_field_order=True)
            ),
        )
        inputs = torch.tensor([ids], device="cuda")
        with torch.inference_mode():
            output = self.model.generate(
                input_ids=inputs,
                attention_mask=torch.ones_like(inputs),
                max_new_tokens=self.max_output,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
                prefix_allowed_tokens_fn=constraint,
            )
        generated = output[0, len(ids) :]
        content = self.tokenizer.decode(generated, skip_special_tokens=True).strip()
        usage = {
            "input_tokens": len(ids),
            "output_tokens": len(generated),
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
