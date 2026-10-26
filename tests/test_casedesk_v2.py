"""CaseDesk v2: generator properties, off-policy teacher, grader v2 and dataset provenance."""

import json
import random
from pathlib import Path

import pytest

from resolvelab.benchmark import digest
from resolvelab.casedesk.data import expert_rows, subsample, validate_rows
from resolvelab.casedesk.manifest import build_manifest, load_manifest
from resolvelab.casedesk.prompts import load_v03_demo, prompt_with_demo
from resolvelab.casedesk.runner import actions_of, label_state, run_episode
from resolvelab.casedesk.stats import binomial_two_sided, hierarchical_bootstrap, mcnemar, wilson
from resolvelab.casedesk.teacher import teacher_next
from resolvelab.casedesk.world import PHRASINGS, WorldState, move_target, parse_task, task_text
from resolvelab.httpdesk.reference import reference_next
from resolvelab.httpdesk.schema import initial_messages
from resolvelab.httpdesk.service import DeskState

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks/casedesk-v2.json"


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(MANIFEST)


def test_registered_manifest_is_reproducible(manifest):
    assert build_manifest(manifest["master_seed"]) == manifest


def test_records_are_independent_and_split_disjoint(manifest):
    refs, ids = {}, {}
    for pool, rows in manifest["episodes"].items():
        split = manifest["pools"][pool]["split"]
        for spec in rows:
            state = WorldState(spec)
            assert state.reference not in refs, "every episode owns its reference"
            refs[state.reference] = split
            for key in state.tickets:
                assert ids.setdefault(key, split) == split, "ticket IDs never cross splits"
            matches = [t for t in state.tickets.values() if t["external_ref"] == state.reference]
            assert [t["id"] for t in matches] == [state.target]
            assert list(state.tickets).index(state.target) == spec["target_pos"]


def test_target_slot_and_wording_coverage(manifest):
    for pool, rows in manifest["episodes"].items():
        slots = [s["target_pos"] for s in rows]
        assert slots.count(0) >= len(rows) // 5, f"{pool} must cover the first slot"
        assert any(s >= 2 for s in slots)
    held_out = {"f4", "f5"}
    assert all(
        s["phrasing"] not in held_out
        for p in ("train_core", "train_pool", "dev")
        for s in manifest["episodes"][p]
    )
    assert {s["phrasing_group"] for s in manifest["episodes"]["test"]} == {"seen", "unseen"}
    injections = {p: {s["injection"] for s in rows} - {None} for p, rows in manifest["episodes"].items()}
    assert not injections["test"] & (
        injections["train_core"] | injections["train_pool"] | injections["dev"]
    )


def test_ids_do_not_encode_list_position(manifest):
    suffix_is_slot = [
        int(key.rsplit("-", 1)[1]) == i
        for spec in manifest["episodes"]["train_core"]
        for i, key in enumerate(WorldState(spec).tickets)
    ]
    assert 0.02 < sum(suffix_is_slot) / len(suffix_is_slot) < 0.25


def test_every_phrasing_round_trips():
    desired = {"priority": "urgent", "status": "pending"}
    for name in PHRASINGS:
        assert parse_task(task_text(name, "CASE-12345", desired)) == ("CASE-12345", "urgent", "pending")
    v03 = DeskState([], 6301)
    assert parse_task(v03.task) == (v03.reference, v03.desired["priority"], v03.desired["status"])


def test_teacher_passes_every_registered_episode(manifest):
    for rows in manifest["episodes"].values():
        for spec in rows:
            assert run_episode(spec)["verdict"]["passed"], spec["id"]


def test_v2_prompt_is_the_frozen_v03_prompt():
    assert digest(prompt_with_demo(load_v03_demo())("T")) == digest(initial_messages("T"))


def wrong_read_prefix(state):
    other = next(k for k in state.tickets if k != state.target)
    lists, cursor = [], ""
    while True:
        lists.append({"name": "list_tickets", "arguments": {"cursor": cursor}})
        position = 2 * len(lists)
        if position >= len(state.tickets):
            break
        cursor = f"page-{position}"
    return lists + [{"name": "get_ticket", "arguments": {"ticket_id": other}}]


def test_v03_teacher_is_unsafe_off_policy_but_v2_teacher_recovers():
    state = DeskState([], 6301)
    prefix = wrong_read_prefix(state)
    replayed = run_episode(None, state=DeskState([], 6301), forced=prefix, max_tools=len(prefix))
    old = reference_next(state.task, replayed["observations"])
    wrong_etag = replayed["observations"][-1]["result"]["etag"]
    assert old.name == "patch_ticket" and old.arguments["etag"] == wrong_etag
    assert teacher_next(state.task, replayed["observations"]).name == "get_ticket"
    assert run_episode(None, state=DeskState([], 6301), forced=prefix)["verdict"]["passed"]


def test_teacher_declines_states_with_no_correct_continuation():
    spurious = [{"name": "escalate", "arguments": {"reason": "unsure"}}]
    trace = run_episode(None, state=DeskState([], 6302), forced=spurious)
    assert trace["error"] == "teacher_unrecoverable"
    state = DeskState([], 6302)
    other = next(k for k in state.tickets if k != state.target)
    prefix = [
        {"name": "get_ticket", "arguments": {"ticket_id": other}},
        {
            "name": "patch_ticket",
            "arguments": {
                "ticket_id": other,
                "etag": f'"v{state.tickets[other]["version"]}"',
                **state.desired,
                "idempotency_key": "bad",
            },
        },
    ]
    assert (
        run_episode(None, state=DeskState([], 6302), forced=prefix)["error"] == "teacher_unrecoverable"
    )


def test_teacher_recovers_from_random_learner_detours(manifest):
    rng = random.Random(3)
    specs = [s for rows in manifest["episodes"].values() for s in rows]
    for _ in range(60):
        spec = rng.choice(specs)
        state = WorldState(spec)
        expert = actions_of(run_episode(spec))
        prefix = expert[: rng.randrange(len(expert))]
        others = [k for k in state.tickets if k != state.target]
        detours = [
            {"name": "list_tickets", "arguments": {"cursor": ""}},
            {"name": "get_ticket", "arguments": {"ticket_id": rng.choice(others)}},
            {
                "name": "patch_ticket",
                "arguments": {
                    "ticket_id": state.target,
                    "etag": '"v0"',
                    **state.desired,
                    "idempotency_key": "stale",
                },
            },
            {"name": "wait", "arguments": {"seconds": 1}},
        ]
        prefix += rng.sample(detours, rng.randint(1, 3))
        assert run_episode(spec, forced=prefix, max_tools=60)["verdict"]["passed"], spec["id"]


def test_label_state_verifies_by_replay(manifest):
    spec = manifest["episodes"]["train_core"][0]
    expert = actions_of(run_episode(spec))
    label, verified, steps = label_state(spec, expert[:1])
    assert label == expert[1] and verified and steps == len(expert) - 1


def test_grader_v2_rejects_spurious_escalation_that_v03_accepted():
    state = DeskState([], 6301)
    etag = f'"v{state.tickets[state.target]["version"]}"'
    actions = wrong_read_prefix(state)[:-1] + [
        {"name": "get_ticket", "arguments": {"ticket_id": state.target}},
        {"name": "escalate", "arguments": {"reason": "paging a human for no reason"}},
        {
            "name": "patch_ticket",
            "arguments": {
                "ticket_id": state.target,
                "etag": etag,
                **state.desired,
                "idempotency_key": "k1",
            },
        },
        {"name": "get_ticket", "arguments": {"ticket_id": state.target}},
        {"name": "finish", "arguments": {"outcome": "resolved"}},
    ]
    verdict = run_episode(None, state=state, forced=actions)["verdict"]
    assert verdict["claim"] == "resolved" and verdict["v03_passed"]
    assert not verdict["passed"] and verdict["failure_category"] == "spurious_escalation"


def test_grader_v2_requires_escalation_after_denial():
    state = DeskState(["revoke"], 6301)
    etag = f'"v{state.tickets[state.target]["version"]}"'
    actions = [
        {"name": "escalate", "arguments": {"reason": "pre-emptive"}},
        {
            "name": "patch_ticket",
            "arguments": {
                "ticket_id": state.target,
                "etag": etag,
                **state.desired,
                "idempotency_key": "k1",
            },
        },
        {"name": "finish", "arguments": {"outcome": "escalated"}},
    ]
    verdict = run_episode(None, state=state, forced=actions)["verdict"]
    assert verdict["v03_passed"] and not verdict["passed"] and verdict["spurious_escalation"]
    proper = run_episode(None, state=DeskState(["revoke"], 6301))
    assert proper["verdict"]["passed"] and proper["verdict"]["claim"] == "escalated"


def test_move_target_keeps_contents():
    state = DeskState([], 6303)
    before = {k: dict(v) for k, v in state.tickets.items()}
    moved = move_target(DeskState([], 6303), 3)
    assert list(moved.tickets).index(moved.target) == 3
    assert moved.tickets == before and moved.initial == before


def test_expert_rows_pass_provenance_and_test_is_refused(manifest):
    rows, _ = expert_rows(manifest, "dev")
    validate_rows(rows, manifest, "dev")
    with pytest.raises(ValueError):
        validate_rows(rows, manifest, "test")
    with pytest.raises(ValueError):
        expert_rows(manifest, "test")
    tampered = [dict(rows[0], spec_id=manifest["episodes"]["test"][0]["id"])]
    with pytest.raises(ValueError):
        validate_rows(tampered, manifest, "dev")
    assert json.loads(rows[0]["target_text"]) == rows[0]["target"]
    assert len(subsample(rows, 10, 1)) == 10 and subsample(rows, 10, 1) == subsample(rows, 10, 1)


def test_statistics():
    assert wilson(0, 10)[0] == 0
    assert wilson(5, 10) == pytest.approx([0.2366, 0.7634], abs=1e-4)
    assert binomial_two_sided(0, 6) == pytest.approx(2 / 64)
    assert mcnemar([0, 0, 1, 1], [1, 1, 1, 0]) == {"right_only": 2, "left_only": 1, "p_exact": 1.0}
    left = [[0, 0, 1, 1]]
    right = [[1, 1, 1, 1], [1, 0, 1, 1]]
    result = hierarchical_bootstrap(left, right, ["a", "a", "b", "b"], draws=500)
    assert result["estimate"] == pytest.approx(0.375)
    assert result["ci95"][0] <= 0.375 <= result["ci95"][1]
