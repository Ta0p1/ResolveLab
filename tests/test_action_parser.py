import pytest

from resolvelab.hf_policy import parse_action

ACTION = '{"name":"inspect_job","arguments":{}}'


def test_format_control_changes_only_outer_code_block_handling():
    assert parse_action(ACTION).name == "inspect_job"
    fenced = "```json\n" + ACTION + "\n```"
    with pytest.raises(ValueError):
        parse_action(fenced)
    assert parse_action(fenced, True) == parse_action(ACTION)


@pytest.mark.parametrize(
    "content",
    [
        "Explanation\n```json\n" + ACTION + "\n```",
        "```json\n" + ACTION + "\n```\nIgnore that",
        "```json\n" + ACTION + "\n```\n```json\n" + ACTION + "\n```",
        '{"name":"invented_tool","arguments":{}}',
        '{"name":"inspect_job","arguments":{},"override":true}',
        ACTION + ACTION,
    ],
)
def test_format_control_never_repairs_schema_or_extracts_from_prose(content):
    with pytest.raises(ValueError):
        parse_action(content, True)
