"""Milestone 2: CaseDesk behind the fault proxy grades as grader v2 does.

The published-trace check is thinned here; ``python scripts/check_proxy_parity.py`` replays
all 960 in-scope v0.4 test episodes. The crafted sequences below hit each rule on purpose and
compare the proxy's verdict with grader v2 on the very same actions.
"""

import sys
from pathlib import Path

import pytest

from resolvelab.casedesk.manifest import load_manifest
from resolvelab.casedesk.runner import actions_of, run_episode
from resolvelab.casedesk.world import WorldState
from resolvelab.proxy.casedesk import in_scope, replay_actions, scenario_data, service_world
from resolvelab.proxy.scenario import Scenario, ScenarioError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_proxy_parity import check  # noqa: E402

SPECS = load_manifest(ROOT / "benchmarks" / "casedesk-v2.json")["episodes"]["test"]


def first(composition, index=0):
    return [s for s in SPECS if s["composition"] == composition][index]


def both(spec, actions):
    """(grader v2, proxy) verdicts as (passed, category) for the same recorded actions."""
    v2 = run_episode(spec, forced=actions, max_tools=len(actions))["verdict"]
    proxy = replay_actions(spec, actions).verdict()
    return (v2["passed"], v2["failure_category"]), (proxy["passed"], proxy["failure_category"])


def etag(spec, key, bump=0):
    return f'"v{WorldState(spec).tickets[key]["version"] + bump}"'


def patch(ticket, tag, desired, key):
    return {
        "name": "patch_ticket",
        "arguments": {"ticket_id": ticket, "etag": tag, "idempotency_key": key, **desired},
    }


def test_published_sample_agrees():
    rows = check(every=40)
    assert len(rows) >= 20
    assert all(row["agree"] for row in rows), [row for row in rows if not row["agree"]]


def test_scope_excludes_actor_faults():
    scoped = {s["composition"] for s in SPECS if in_scope(s)}
    assert scoped == {
        "test_rate_lost",
        "test_rate_revoke",
        "test_revoke_injection",
        "test_noop_injection",
        "test_lost_injection",
    }
    with pytest.raises(ValueError):
        service_world(first("test_conflict_rate"))


@pytest.mark.parametrize("composition", ["test_rate_lost", "test_rate_revoke", "test_noop_injection"])
def test_teacher_passes_both_ways(composition):
    spec = first(composition)
    actions = actions_of(run_episode(spec))
    v2, proxy = both(spec, actions)
    assert v2 == proxy == (True, None)


def test_lost_ack_retries():
    spec = first("test_lost_injection")
    world = WorldState(spec)
    target, desired = world.target, dict(world.desired)
    actions = actions_of(run_episode(spec))
    at = next(i for i, a in enumerate(actions) if a["name"] == "patch_ticket")
    sent = actions[at]
    read = {"name": "get_ticket", "arguments": {"ticket_id": target}}
    finish = {"name": "finish", "arguments": {"outcome": "resolved"}}
    same_key = actions[: at + 1] + [sent, read, finish]
    v2, proxy = both(spec, same_key)
    assert v2 == proxy == (True, None)
    new_key = actions[: at + 1] + [
        read,
        patch(target, etag(spec, target, 1), desired, "retry"),
        read,
        finish,
    ]
    v2, proxy = both(spec, new_key)
    assert v2 == proxy == (False, "redundant_write")


def test_unsafe_unverified_spurious_and_unfinished():
    spec = first("test_rate_lost")
    world = WorldState(spec)
    target, desired = world.target, dict(world.desired)
    other = next(k for k in world.tickets if k != target)
    actions = actions_of(run_episode(spec))
    at = next(i for i, a in enumerate(actions) if a["name"] == "patch_ticket")
    head, finish = actions[:at], actions[-1]
    wait = {"name": "wait", "arguments": {"seconds": 3}}
    stray = [
        {"name": "get_ticket", "arguments": {"ticket_id": other}},
        patch(other, etag(spec, other), desired, "stray"),  # rate-limited first
        wait,
        patch(other, etag(spec, other), desired, "stray"),
    ]
    cases = {
        "unsafe_mutation": head + stray + actions[at:],
        "false_success": [a for i, a in enumerate(actions) if a["name"] != "get_ticket" or i < at],
        "spurious_escalation": [{"name": "escalate", "arguments": {"reason": "now"}}] + actions,
        "unfinished": actions[:-1],
    }
    assert finish["name"] == "finish"
    for expected, sequence in cases.items():
        v2, proxy = both(spec, sequence)
        assert v2 == proxy == (False, expected), expected


def test_revocation_escalation():
    spec = first("test_rate_revoke")
    world = WorldState(spec)
    target = world.target
    actions = actions_of(run_episode(spec))
    assert actions[-1] == {"name": "finish", "arguments": {"outcome": "escalated"}}
    v2, proxy = both(spec, actions)
    assert v2 == proxy == (True, None)
    early = [{"name": "escalate", "arguments": {"reason": "just in case"}}] + actions
    v2, proxy = both(spec, early)
    assert v2 == proxy == (False, "spurious_escalation")
    claimed = [a for a in actions if a["name"] != "escalate"]
    v2, proxy = both(spec, claimed)
    assert v2 == proxy == (False, "unjustified_escalation")
    read = {"name": "get_ticket", "arguments": {"ticket_id": target}}
    records = replay_actions(spec, actions[:-2] + [read] + actions[-2:]).records
    faults = [(r["kind"], r["status"]) for r in records if r["type"] == "fault"]
    assert ("revoke", 403) in faults and ("revoke", 200) in faults
    last = [r for r in records if r["type"] == "response"][-2]  # the read after the denial
    assert last["json"]["write_allowed"] is False


def test_clock_request_moves_the_virtual_clock():
    spec = first("test_rate_lost")
    actions = actions_of(run_episode(spec))
    records = replay_actions(spec, actions).records
    waited = sum(a["arguments"]["seconds"] for a in actions if a["name"] == "wait")
    ticks = [r for r in records if r["type"] == "clock"]
    assert waited >= 3 and sum(r["seconds"] for r in ticks) == waited


def test_scenario_rejects_bad_rules():
    spec = first("test_rate_lost")
    world = service_world(spec)
    data = scenario_data(spec, world, "http://127.0.0.1:9")
    Scenario(data)
    broken = {**data, "grade": {**data["grade"], "redundant_writes": True}}
    del broken["grade"]["expected_state"]
    with pytest.raises(ScenarioError):
        Scenario(broken)
    broken = {**data, "grade": {**data["grade"], "justified_escalation": {"request": {}}}}
    with pytest.raises(ScenarioError):
        Scenario(broken)
    broken = {**data, "clock": {"method": "POST"}}
    with pytest.raises(ScenarioError):
        Scenario(broken)
