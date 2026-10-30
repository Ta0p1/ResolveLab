"""The v0.4 constrained decoder, with the schema of the episode's dialect.

Decoding is the v0.4 ``ConstrainedPolicy`` path (greedy, or seeded sampling for DAgger
rollouts; no thinking): the chat template without thinking, LM Format Enforcer with field
order forced, the same token budgets. Only the grammar changes per episode, and the output
is validated against the dialect instead of the study contract. The policy returns the
dialect action; ``run_dialect_episode`` translates it.
"""

import json
import time

from ..benchmark import digest
from ..casedesk.policy import ConstrainedPolicy
from ..hf_policy import prompt_ids
from ..policies import PolicyResponseError
from .translate import Translator


class DialectPolicy(ConstrainedPolicy):
    def __init__(self, config, adapter=None, *, temperature=None, seed=0):
        super().__init__(config, adapter, temperature=temperature, seed=seed)
        self.translator = None
        self.metadata.update(
            {"protocol": "casedesk_dialect_json_schema_v1", "schema_sha256": None, "prompt_sha256": None}
        )

    def set_dialect(self, dialect):
        """Called by ``run_dialect_episode`` before the first step of every episode."""
        self.translator = Translator(dialect)
        self.schema = self.translator.schema()

    def next(self, messages):
        from lmformatenforcer import CharacterLevelParserConfig, JsonSchemaParser
        from lmformatenforcer.integrations.transformers import (
            build_transformers_prefix_allowed_tokens_fn,
        )

        if self.translator is None:
            raise RuntimeError("set_dialect() must be called before the first action")
        start = time.perf_counter()
        self.calls += 1
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
        sampling = None
        if self.temperature is not None:
            sampling = {"temperature": self.temperature, "top_p": 1.0, "top_k": 0}
        generated = self.generate(ids, self.max_output, constraint, sampling=sampling)
        content = self.tokenizer.decode(generated, skip_special_tokens=True).strip()
        usage = {
            "input_tokens": len(ids),
            "output_tokens": len(generated),
            "raw_output": content,
            "json_valid": False,
            "schema_valid": False,
            "schema_sha256": digest(self.schema),
        }
        seconds = time.perf_counter() - start
        try:
            value = json.loads(content)
            usage["json_valid"] = True
            self.translator.validate(value)
            usage["schema_valid"] = True
        except (ValueError, TypeError) as exc:
            usage["failure_category"] = "schema_error" if usage["json_valid"] else "json_error"
            raise PolicyResponseError(str(exc)[:300], usage, seconds) from exc
        return value, usage, seconds
