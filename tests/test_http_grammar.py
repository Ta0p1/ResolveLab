"""Exercise the actual optional grammar engine, including cross-tool argument binding."""

import json

import pytest

from resolvelab.httpdesk.schema import action_schema


def accepts(value):
    engine = pytest.importorskip("lmformatenforcer")
    parser = engine.JsonSchemaParser(
        action_schema(), config=engine.CharacterLevelParserConfig(force_json_field_order=True)
    )
    for char in json.dumps(value):
        if char not in parser.get_allowed_characters():
            return False
        parser = parser.add_character(char)
    return parser.can_end()


def test_grammar_covers_every_tool_without_choosing_actions():
    examples = [
        {"name": "list_tickets", "arguments": {"cursor": "invented-but-type-valid"}},
        {"name": "get_ticket", "arguments": {"ticket_id": "wrong-ticket-still-legal"}},
        {
            "name": "patch_ticket",
            "arguments": {
                "ticket_id": "x",
                "etag": "v-wrong",
                "priority": "urgent",
                "status": "resolved",
                "idempotency_key": "k",
            },
        },
        {"name": "wait", "arguments": {"seconds": 3}},
        {"name": "escalate", "arguments": {"reason": "possibly unjustified"}},
        {"name": "finish", "arguments": {"outcome": "resolved"}},
    ]
    assert all(accepts(x) for x in examples)
    assert not accepts({"name": "get_ticket", "arguments": {"cursor": ""}})
    assert not accepts({"name": "not_a_tool", "arguments": {}})
    assert not accepts({"name": "finish", "arguments": {"outcome": "success"}})
