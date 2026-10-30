"""API dialects: canonical parity, lexical disjointness and fault semantics under translation."""

import json
import re
import zipfile
from pathlib import Path

import pytest

from resolvelab.casedesk.manifest import episodes, load_manifest
from resolvelab.casedesk.runner import actions_of, run_episode
from resolvelab.casedesk.world import PHRASINGS, task_text
from resolvelab.dialects import (
    CANONICAL,
    Dialect,
    Translator,
    dialect_actions,
    generate,
    initial_messages,
    run_dialect_episode,
    system_prompt,
)
from resolvelab.dialects import task_text as dialect_task_text
from resolvelab.dialects.spec import ENVELOPE
from resolvelab.httpdesk import schema

ROOT = Path(__file__).resolve().parents[1]
TRACES = ROOT / "artifacts/v0.4/traces/test"
VALID_CURSOR = re.compile(r"^(|page-\d*[02468])$")


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(ROOT / "benchmarks/casedesk-v2.json")


def spec_with(manifest, pool, composition):
    return next(s for s in episodes(manifest, pool) if s["composition"] == composition)


def dialect_with(split="train", **conventions):
    for seed in range(500):
        dialect = generate(seed, split)
        if all(getattr(dialect, k) == v for k, v in conventions.items()):
            return dialect
    raise LookupError(conventions)


def published(archive, limit=None):
    with zipfile.ZipFile(TRACES / archive) as bundle:
        names = sorted(bundle.namelist())[:limit]
        return [json.loads(bundle.read(name)) for name in names]


class Scripted:
    def __init__(self, *actions):
        self.actions = list(actions)

    def next(self, messages):
        return self.actions.pop(0), {}, 0


# -- the canonical dialect is the study ----------------------------------------------------


@pytest.mark.parametrize("phrasing", sorted(PHRASINGS))
def test_canonical_prompt_is_the_study_prompt(phrasing):
    desired = {"priority": "urgent", "status": "pending"}
    task = task_text(phrasing, "CASE-12345", desired)
    assert dialect_task_text(CANONICAL, phrasing, "CASE-12345", desired) == task
    assert initial_messages(CANONICAL, task) == schema.initial_messages(task)
    assert Translator(CANONICAL).schema() == schema.action_schema()


def test_canonical_episodes_match_the_study_runner(manifest):
    for composition in (
        "dev_conflict_injection",
        "dev_rate_injection",
        "dev_revoke_lost",
        "dev_noop_rate",
    ):
        spec = spec_with(manifest, "dev", composition)
        study = run_episode(spec, keep_messages=True)
        ours = run_dialect_episode(spec, CANONICAL, keep_messages=True)
        assert ours["steps"] == study["steps"]
        assert ours["observations"] == study["observations"]
        assert ours["verdict"] == study["verdict"] and study["verdict"]["passed"]


def test_canonical_observations_are_identity_on_every_published_result():
    translator = Translator(CANONICAL)
    statuses = set()
    for archive in sorted(TRACES.glob("*.zip")):
        for trace in published(archive.name):
            for obs in trace["observations"]:
                assert translator.observe(obs["name"], obs["result"]) == obs["result"]
                statuses.add(obs["result"].get("status"))
    assert {0, 200, 201, 400, 403, 404, 412, 429, 502} <= statuses, "every error path is covered"


def test_published_model_traces_replay_through_a_dialect(manifest):
    """The study's own model actions, rewritten into a dialect, meet the same service state."""
    dialect = dialect_with(token="revision", cursor="offset", unit="milliseconds")
    translator = Translator(dialect)
    replayed = 0
    for trace in published("bc-42.zip"):
        actions = actions_of(trace)
        cursors = [a["arguments"]["cursor"] for a in actions if a["name"] == "list_tickets"]
        tokens = [a["arguments"]["etag"] for a in actions if a["name"] == "patch_ticket"]
        if not all(VALID_CURSOR.match(c) for c in cursors) or not all(
            re.fullmatch(r'"v\d+"', t) for t in tokens
        ):
            continue
        written = [translator.from_canonical(a) for a in actions]
        assert [translator.to_canonical(w) for w in written] == actions
        ours = run_dialect_episode(trace["spec"], dialect, forced=written, max_tools=len(written))
        assert [o["result"] for o in ours["observations"]] == [
            o["result"] for o in trace["observations"]
        ]
        assert ours["verdict"] == trace["verdict"]
        replayed += 1
        if replayed == 4:
            break
    assert replayed == 4


# -- generated dialects ----------------------------------------------------------------------


def test_heldout_identifiers_are_disjoint_from_train_and_canonical():
    train, heldout = set(), set()
    for seed in range(300):
        train |= generate(seed, "train").identifiers()
        heldout |= generate(seed, "heldout").identifiers()
    assert not train & heldout
    assert not CANONICAL.identifiers() & heldout


def test_generation_is_deterministic_and_varies_every_convention():
    assert generate(7, "train") == generate(7, "train")
    drawn = [generate(seed, "heldout") for seed in range(60)]
    for convention in ("token", "cursor", "unit"):
        assert len({getattr(d, convention) for d in drawn}) > 1
    assert len({d.codes[412] for d in drawn}) == 2


def test_colliding_names_are_rejected():
    tools = dict(CANONICAL.tools, wait="finish")
    with pytest.raises(ValueError, match="duplicate tools"):
        Dialect(**{**CANONICAL.__dict__, "tools": tools})
    args = dict(CANONICAL.args, idempotency_key="ticket_id")
    with pytest.raises(ValueError, match="duplicate arguments"):
        Dialect(**{**CANONICAL.__dict__, "args": args})


def test_heldout_prompt_never_shows_a_canonical_identifier():
    """No canonical name in the catalog or demo; the rules' prose keeps plain English words."""
    canonical = CANONICAL.identifiers() - ENVELOPE
    compound = {w for w in canonical if "_" in w}
    for seed in range(6):
        dialect = generate(seed, "heldout")
        messages = initial_messages(dialect, "New task")
        rules, catalog = messages[0]["content"].split("\nTools:\n", 1)
        assert not {w for w in compound if w in rules}
        seen = _keys_and_enums(json.loads(catalog)) - {"string", "integer", "object"}
        for message in messages[1:-1]:
            value = json.loads(message["content"]) if message["content"].startswith("{") else {}
            seen |= _keys_and_enums(value)
        assert not seen & canonical, seen & canonical


def _keys_and_enums(value):
    if isinstance(value, dict):
        found = set(value)
        for item in value.values():
            found |= _keys_and_enums(item)
        return found
    if isinstance(value, list):
        return set().union(*map(_keys_and_enums, value)) if value else set()
    return {value} if isinstance(value, str) and re.fullmatch(r"[a-z_]+", value) else set()


@pytest.mark.parametrize("split", ["train", "heldout"])
def test_teacher_solves_fault_compositions_in_generated_dialects(manifest, split):
    specs = [spec_with(manifest, "dev", c) for c in ("dev_conflict_injection", "dev_revoke_lost")]
    specs += [
        spec_with(manifest, "test", c) for c in ("test_conflict_rate_lost", "test_concurrent_rate")
    ]
    for seed in range(3):
        dialect = generate(seed, split)
        for spec in specs:
            trace = run_dialect_episode(spec, dialect)
            assert trace["verdict"]["passed"], (dialect.name, spec["id"], trace["verdict"])
            assert trace["observations"] and dialect_actions(trace)


@pytest.mark.parametrize("token", ["etag", "revision", "weak_etag", "version_tag"])
def test_a_mangled_token_is_a_conflict_and_never_commits(manifest, token):
    spec = spec_with(manifest, "train_core", "train_plain")
    dialect = dialect_with(token=token)
    written = dialect_actions(run_dialect_episode(spec, dialect))
    patch = next(i for i, a in enumerate(written) if a["name"] == dialect.tools["patch_ticket"])
    bad = json.loads(json.dumps(written[patch]))
    key = dialect.args["etag"]
    bad["arguments"][key] = (
        bad["arguments"][key] + 1 if token == "revision" else bad["arguments"][key] + "x"
    )
    trace = run_dialect_episode(spec, dialect, forced=written[:patch] + [bad], max_tools=patch + 1)
    assert trace["observations"][-1]["result"]["status"] == 412
    assert trace["commits"] == []
    shown = Translator(dialect).observe("patch_ticket", trace["observations"][-1]["result"])
    assert shown["status"] == dialect.codes[412]
    assert shown["body"]["error"] == dialect.errors["precondition_failed"]


def test_millisecond_dialects_translate_waits_and_hints(manifest):
    spec = spec_with(manifest, "train_core", "train_rate")
    dialect = dialect_with(unit="milliseconds", split="heldout")
    trace = run_dialect_episode(spec, dialect, keep_messages=True)
    assert trace["verdict"]["passed"]
    limited = [o for o in trace["observations"] if o["result"].get("status") == 429]
    shown = Translator(dialect).observe("patch_ticket", limited[0]["result"])
    assert shown["status"] == dialect.codes[429]
    assert shown[dialect.fields["retry_after"]] == 1000 * int(limited[0]["result"]["retry_after"])
    waits = [a for a in dialect_actions(trace) if a["name"] == dialect.tools["wait"]]
    assert waits and all(a["arguments"][dialect.args["seconds"]] % 1000 == 0 for a in waits)


def test_opaque_cursors_are_per_episode_and_unknown_ones_are_rejected(manifest):
    spec = next(s for s in episodes(manifest, "dev") if s["target_pos"] >= 2)
    dialect = dialect_with(cursor="opaque")
    translator = Translator(dialect, seed=spec["id"])
    assert translator.page_token != Translator(dialect, seed="other").page_token
    listing = {
        "name": dialect.tools["list_tickets"],
        "arguments": {dialect.args["cursor"]: "pg_made_up"},
    }
    trace = run_dialect_episode(spec, dialect, forced=[listing], max_tools=1)
    shown = translator.observe("list_tickets", trace["observations"][0]["result"])
    assert shown["status"] == 400
    assert shown["body"]["error"] == dialect.errors["invalid_cursor"]
    good = run_dialect_episode(spec, dialect, keep_messages=True)
    assert good["verdict"]["passed"]
    listings = [w for w in dialect_actions(good) if w["name"] == dialect.tools["list_tickets"]]
    pages = [w["arguments"][dialect.args["cursor"]] for w in listings]
    assert pages[0] == "" and all(p.startswith("pg_") for p in pages[1:])


def test_invalid_dialect_actions_stop_before_any_request(manifest):
    spec = spec_with(manifest, "dev", "dev_noop_rate")
    dialect = generate(0, "heldout")
    canonical = {"name": "list_tickets", "arguments": {"cursor": ""}}
    for action in (
        canonical,
        {"name": dialect.tools["finish"], "arguments": {}},
        ["not", "an", "action"],
    ):
        trace = run_dialect_episode(spec, dialect, policy=Scripted(action))
        assert trace["error"] == "invalid_action"
        assert trace["http_client"] == [] and not trace["verdict"]["passed"]


def test_system_prompt_lists_every_tool_with_its_dialect_schema():
    dialect = generate(1, "heldout")
    catalog = json.loads(system_prompt(dialect).split("\nTools:\n", 1)[1])
    assert [tool["name"] for tool in catalog] == list(dialect.tools.values())
    translator = Translator(dialect)
    for tool in catalog:
        canonical = translator.tool_of[tool["name"]]
        assert tool["parameters"] == translator.parameters(canonical)
