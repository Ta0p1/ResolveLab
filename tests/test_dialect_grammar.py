"""The actual optional grammar engine on dialect schemas (runs in the training environment)."""

import json

import pytest

from resolvelab.casedesk.manifest import episodes, load_manifest
from resolvelab.dialects import CANONICAL, Translator, dialect_actions, generate, run_dialect_episode
from resolvelab.httpdesk.schema import action_schema


def accepts(schema, value):
    engine = pytest.importorskip("lmformatenforcer")
    parser = engine.JsonSchemaParser(
        schema, config=engine.CharacterLevelParserConfig(force_json_field_order=True)
    )
    for char in json.dumps(value):
        if char not in parser.get_allowed_characters():
            return False
        parser = parser.add_character(char)
    return parser.can_end()


def first(split, **conventions):
    return next(
        d
        for d in map(lambda seed: generate(seed, split), range(500))
        if all(getattr(d, k) == v for k, v in conventions.items())
    )


def test_canonical_dialect_grammar_is_the_study_grammar():
    assert Translator(CANONICAL).schema() == action_schema()


@pytest.mark.parametrize("token", ["etag", "revision", "weak_etag", "version_tag"])
def test_grammar_admits_every_teacher_action_and_nothing_canonical(token):
    pytest.importorskip("lmformatenforcer")
    from pathlib import Path

    manifest = load_manifest(Path(__file__).resolve().parents[1] / "benchmarks/casedesk-v2.json")
    spec = next(s for s in episodes(manifest, "dev") if s["composition"] == "dev_rate_injection")
    dialect = first("heldout", token=token)
    schema = Translator(dialect).schema()
    written = dialect_actions(run_dialect_episode(spec, dialect))
    assert written and all(accepts(schema, a) for a in written)
    assert not accepts(schema, {"name": "list_tickets", "arguments": {"cursor": ""}})
    patch = next(a for a in written if a["name"] == dialect.tools["patch_ticket"])
    key = dialect.args["etag"]
    wrong_type = str(patch["arguments"][key]) if token == "revision" else 7
    assert not accepts(schema, patch | {"arguments": patch["arguments"] | {key: wrong_type}})
    # Like the study grammar, values are typed but never chosen: a stale token is still legal.
    stale = patch["arguments"][key] + 1 if token == "revision" else patch["arguments"][key] + "0"
    assert accepts(schema, patch | {"arguments": patch["arguments"] | {key: stale}})
