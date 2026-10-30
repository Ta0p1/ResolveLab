"""Shared pieces for model providers: the portable action schema and response parsing.

Every provider implements ``next(messages) -> (action, usage, seconds)`` over the same
conversation the HF arms see (system prompt, one-shot demo, task, then alternating actions
and observations). A provider never repairs, retries or replaces a model's decision: text
that is not a valid action raises ``PolicyResponseError`` and the episode ends as a failure.
"""

import json

from ..httpdesk.schema import ARGUMENTS, validate_action
from ..policies import PolicyResponseError

DROPPED_KEYWORDS = {"title", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "default"}


def _clean(schema):
    if isinstance(schema, dict):
        return {k: _clean(v) for k, v in schema.items() if k not in DROPPED_KEYWORDS}
    if isinstance(schema, list):
        return [_clean(v) for v in schema]
    return schema


def portable_schema():
    """The action schema in the shape hosted structured-output APIs accept.

    The study schema (``httpdesk.schema.action_schema``) is a root ``anyOf`` of six objects.
    Hosted APIs require an object at the root, so here ``name`` is an enum of the six tools
    and ``arguments`` an ``anyOf`` of their argument schemas: the model still emits exactly
    ``{"name": ..., "arguments": {...}}``, and ``validate_action`` rejects a name paired with
    another tool's arguments. Numeric bounds and titles are dropped because not every API
    supports them; the same validation enforces them afterwards.
    """
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "enum": list(ARGUMENTS)},
            "arguments": {"anyOf": [_clean(cls.model_json_schema()) for cls in ARGUMENTS.values()]},
        },
        "required": ["name", "arguments"],
        "additionalProperties": False,
    }


def parse_action(text, usage, seconds):
    """Validate model text as one tool action; never repair it."""
    usage = {**usage, "raw_output": text, "json_valid": False, "schema_valid": False}
    try:
        value = json.loads(text)
        usage["json_valid"] = True
        action = validate_action(value)
        usage["schema_valid"] = True
    except (ValueError, TypeError) as exc:
        usage["failure_category"] = "schema_error" if usage["json_valid"] else "json_error"
        raise PolicyResponseError(str(exc)[:300], usage, seconds) from exc
    return action, usage, seconds


def fail(category, message, usage, seconds):
    raise PolicyResponseError(message, {**usage, "failure_category": category}, seconds)


def split_system(messages):
    """(system text, remaining messages) for APIs that take the system prompt separately."""
    if not messages or messages[0]["role"] != "system":
        return None, list(messages)
    return messages[0]["content"], list(messages[1:])
