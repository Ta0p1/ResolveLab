"""Durable CaseDesk: persisted receipts, crash points, restarts, two-worker races, exactly-once.

Every episode here runs real uvicorn worker processes on a shared SQLite store. A crash is a
process exit (``os._exit``) inside the request; a restart is a kill followed by a new process.
"""

import copy
import functools
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from resolvelab.casedesk.manifest import load_manifest
from resolvelab.casedesk.runner import actions_of, run_episode
from resolvelab.casedesk.world import WorldState
from resolvelab.durable.cli import main as durable_cli
from resolvelab.durable.counterexamples import claim_after_crash, new_key_retry, stale_etag_retry
from resolvelab.durable.episodes import (
    COMPOSITIONS,
    PROCESS_FAULTS,
    build_episodes,
    validate_spec,
)
from resolvelab.durable.grading import grade_durable
from resolvelab.durable.race import race
from resolvelab.durable.runner import run_durable_episode
from resolvelab.durable.service import EXIT_CODES

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = load_manifest(ROOT / "benchmarks/casedesk-v2.json")
V2 = {spec["id"]: spec for rows in MANIFEST["episodes"].values() for spec in rows}
EPISODES = {spec["id"]: spec for spec in build_episodes()}


def spec_of(composition):
    return EPISODES[f"durable-{composition}-00"]


@functools.cache
def teacher(composition, store="durable"):
    return run_durable_episode(spec_of(composition), store=store)


@functools.cache
def scripted(composition, policy):
    return run_durable_episode(spec_of(composition), policy=policy)


def statuses(trace):
    return [(o["name"], o["result"].get("status")) for o in trace["observations"]]


def boots(trace):
    return [(b["kind"], b["ended_by"]) for b in trace["boots"]]


def target_write(spec, key):
    """get, then patch the target with ``key``: the first two actions of a direct episode."""
    world = WorldState(spec)
    etag = f'"v{world.tickets[world.target]["version"]}"'
    get = {"name": "get_ticket", "arguments": {"ticket_id": world.target}}
    patch = {
        "name": "patch_ticket",
        "arguments": {"ticket_id": world.target, "etag": etag, "idempotency_key": key, **world.desired},
    }
    return world, get, patch


FINISH = {"name": "finish", "arguments": {"outcome": "resolved"}}


# -- the experiment --------------------------------------------------------------------------


def test_episodes_are_reproducible_valid_and_use_unregistered_records():
    assert build_episodes() == build_episodes()
    registered = {spec["record_seed"] for spec in V2.values()}
    assert {s["composition"] for s in EPISODES.values()} == {c for c, _, _ in COMPOSITIONS}
    for spec in EPISODES.values():
        assert validate_spec(spec) is spec
        assert spec["record_seed"] not in registered
        world = WorldState(spec)
        # Every episode needs a write, so every process fault in it has a commit to fire on.
        assert world.tickets[world.target]["priority"] != world.desired["priority"] or (
            world.tickets[world.target]["status"] != world.desired["status"]
        )


@pytest.mark.parametrize(
    "faults, workers",
    [
        (["duplicate_delivery"], 1),
        (["duplicate_delivery", "crash_after_commit"], 2),
        (["duplicate_delivery", "lost_ack"], 2),
        (["crash_after_commit", "crash_after_commit"], 1),
        (["power_loss"], 1),
        (["conflict", "concurrent_resolve"], 1),
        ([], 3),
    ],
)
def test_ambiguous_or_unknown_compositions_are_refused(faults, workers):
    with pytest.raises(ValueError):
        validate_spec({**spec_of("crash_after"), "faults": faults, "workers": workers})


# -- fidelity: the frozen handlers on a persisted store --------------------------------------


@pytest.mark.parametrize(
    "episode, workers",
    [
        ("test-test_conflict_rate_lost-00", 1),
        ("test-test_rate_revoke-01", 1),
        ("test-test_concurrent_injection-02", 1),
        ("dev-dev_noop_rate-03", 1),
        ("test-test_conflict_rate_lost-00", 2),
        ("test-test_rate_revoke-01", 2),
    ],
)
def test_without_process_faults_it_behaves_exactly_like_the_in_memory_service(episode, workers):
    spec = V2[episode]
    reference = run_episode(spec)
    trace = run_durable_episode({**spec, "workers": workers})
    assert trace["observations"] == reference["observations"]
    assert {k: trace["verdict"][k] for k in reference["verdict"]} | {"grader": "casedesk_v2"} == {
        **reference["verdict"],
        "grader": "casedesk_v2",
    }
    assert trace["verdict"]["passed"] == trace["verdict"]["v2_passed"] is True
    assert [{k: c[k] for k in ("id", "before", "after")} for c in trace["commits"]] == reference[
        "commits"
    ]
    assert trace["final_state"] == reference["final_state"]
    assert trace["diagnostics"]["faults_exposed"] == reference["diagnostics"]["faults_exposed"]
    if workers == 2:
        assert {r["worker"] for r in trace["http_client"]} == {0, 1}


@pytest.mark.parametrize("arm", ["bc-volume-2026", "dagger-2026"])
def test_published_model_traces_replay_identically_on_the_durable_store(arm):
    report = json.loads((ROOT / "artifacts/v0.4/test" / f"{arm}.json").read_text(encoding="utf-8"))
    traces = zipfile.ZipFile(ROOT / "artifacts/v0.4/traces/test" / f"{arm}.zip")
    recorded = [json.loads(traces.read(row["trace"])) for row in report["rows"]]
    # Forced actions must be tool calls, so episodes an invalid model output ended are left out.
    valid = [t for t in recorded if all("action" in d for d in t["decisions"])]
    failures = [t for t in valid if not t["verdict"]["passed"]]
    assert failures, "the replay must include failed episodes"
    for record in valid[::40] + failures[:3]:
        actions = actions_of(record)
        trace = run_durable_episode(V2[record["spec"]["id"]], forced=actions, max_tools=len(actions))
        assert trace["observations"] == record["observations"], record["spec"]["id"]
        assert trace["verdict"]["v2_passed"] == record["verdict"]["passed"], record["spec"]["id"]
        assert trace["verdict"]["failure_category"] == record["verdict"]["failure_category"]
        assert trace["error"] == record["error"]


# -- the teacher on every composition --------------------------------------------------------


@pytest.mark.parametrize("composition", [c for c, _, _ in COMPOSITIONS])
def test_the_teacher_passes_every_process_fault_composition(composition):
    spec, trace = spec_of(composition), teacher(composition)
    verdict = trace["verdict"]
    assert verdict["passed"] and verdict["exactly_once"], verdict
    assert verdict["duplicate_key_commits"] == verdict["lost_commits"] == 0
    planned = sorted(set(spec["faults"]) & PROCESS_FAULTS)
    assert trace["diagnostics"]["process_faults_fired"] == planned
    # A crash restarts the worker it killed; a scheduled restart restarts every worker.
    crashes = sum(f in EXIT_CODES for f in planned)
    assert verdict["restarts"] == crashes + spec["workers"] * ("restart_after_commit" in planned)
    assert verdict["commits"] == (0 if "revoke" in spec["faults"] else 1)


# -- crash points ----------------------------------------------------------------------------


def test_crash_after_commit_keeps_the_write_and_a_replayed_key_gets_the_saved_response():
    spec = spec_of("crash_after")
    world, get, patch = target_write(spec, "op-1")
    trace = run_durable_episode(spec, forced=[get, patch, patch, get, FINISH])
    assert statuses(trace) == [
        ("get_ticket", 200),
        ("patch_ticket", 0),
        ("patch_ticket", 200),
        ("get_ticket", 200),
        ("finish", None),
    ]
    assert trace["observations"][1]["result"]["commit_state"] == "unknown"
    # The replay crossed a restart and still found its receipt: the saved 200, not a 412.
    assert trace["observations"][2]["result"]["body"] == {"updated": world.target}
    assert boots(trace) == [("start", "crash_after_commit"), ("restart", "stopped"), ("final", None)]
    assert trace["boots"][0]["exit_code"] == EXIT_CODES["crash_after_commit"]
    patches = [e for e in trace["http_server"] if e["method"] == "PATCH"]
    assert [(e["status"], e["delivered"], e["boot"]) for e in patches] == [
        (200, False, 1),
        (200, True, 2),
    ]
    assert [c["key"] for c in trace["commits"]] == ["op-1"]
    assert trace["boots"][1]["recovered"][world.target] == trace["commits"][0]["after"]["version"]
    assert trace["verdict"]["passed"] and trace["verdict"]["restarts"] == 1


def test_without_persisted_receipts_the_same_replay_commits_twice():
    spec = spec_of("crash_after")
    _, get, patch = target_write(spec, "op-1")
    trace = run_durable_episode(spec, forced=[get, patch, patch, get, FINISH], store="process")
    assert statuses(trace)[2] == ("patch_ticket", 200)
    assert [c["key"] for c in trace["commits"]] == ["op-1", "op-1"]
    verdict = trace["verdict"]
    assert not verdict["passed"] and verdict["failure_category"] == "duplicate_commit"
    assert verdict["duplicate_key_commits"] == 1 and verdict["lost_acknowledged_commits"] == 1


def test_crash_before_commit_leaves_no_write_no_receipt_and_no_event():
    spec = spec_of("crash_before")
    world, get, patch = target_write(spec, "op-1")
    trace = run_durable_episode(spec, forced=[get, patch, get, patch, get, FINISH])
    assert statuses(trace) == [
        ("get_ticket", 200),
        ("patch_ticket", 0),
        ("get_ticket", 200),
        ("patch_ticket", 200),
        ("get_ticket", 200),
        ("finish", None),
    ]
    before, after = trace["observations"][0]["result"], trace["observations"][2]["result"]
    assert after == before, "the crashed write never happened"
    assert boots(trace)[0] == ("start", "crash_before_commit")
    assert trace["boots"][0]["exit_code"] == EXIT_CODES["crash_before_commit"]
    # The same key commits on the retry: the receipt was rolled back with the write.
    assert [(c["key"], c["boot"]) for c in trace["commits"]] == [("op-1", 2)]
    assert [(e["method"], e["boot"]) for e in trace["http_server"]] == [
        ("GET", 1),
        ("GET", 2),
        ("PATCH", 2),
        ("GET", 2),
    ]
    assert trace["verdict"]["passed"]


def test_both_crash_points_in_one_episode_fire_once_each():
    trace = teacher("crash_before_after")
    patches = [s for s in statuses(trace) if s[0] == "patch_ticket"]
    assert patches == [("patch_ticket", 0), ("patch_ticket", 0)]
    assert [b[1] for b in boots(trace)[:2]] == ["crash_before_commit", "crash_after_commit"]
    assert len(trace["commits"]) == 1 and trace["verdict"]["passed"]


# -- restart ---------------------------------------------------------------------------------


def test_after_a_restart_the_agent_continues_on_the_same_store():
    trace = teacher("restart")
    names = statuses(trace)
    write = names.index(("patch_ticket", 200))
    # The next request finds the service down; the one after reaches the restarted process.
    assert names[write + 1 : write + 3] == [("get_ticket", 0), ("get_ticket", 200)]
    assert trace["observations"][write + 1]["result"]["error"] == "ConnectError"
    assert boots(trace) == [("start", "killed"), ("restart", "stopped"), ("final", None)]
    final = trace["observations"][write + 2]["result"]["body"]
    assert {k: final[k] for k in ("priority", "status")} == WorldState(spec_of("restart")).desired
    assert trace["verdict"]["passed"] and trace["verdict"]["fresh_after_restart"]


def test_a_process_local_store_loses_the_acknowledged_write_on_restart():
    trace = teacher("restart", "process")
    names = statuses(trace)
    write = names.index(("patch_ticket", 200))
    reread = trace["observations"][write + 2]["result"]
    assert reread["etag"] == trace["observations"][write - 1]["result"]["etag"], "the write is gone"
    verdict = trace["verdict"]
    assert not verdict["passed"] and verdict["failure_category"] == "lost_acknowledged_commit"
    assert verdict["lost_acknowledged_commits"] >= 1


# -- two workers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case, expected",
    [
        ("same_key", [200, 200, 200, 200]),
        ("new_keys", [200, 412, 412, 412]),
        ("key_reuse", [200, 200, 409, 409]),
    ],
)
def test_concurrent_patches_on_two_workers_commit_exactly_once(case, expected):
    responses, snapshot = race(case, hold_ms=300)
    assert sorted(r["status"] for r in responses) == expected
    assert len(snapshot.commits) == 1
    assert len(snapshot.receipts) == 1
    winners = [r for r in responses if r["status"] == 200]
    assert all(r["body"] == winners[0]["body"] for r in winners)
    served = {e["boot"] for e in snapshot.http_events if e["method"] == "PATCH"}
    assert served == {1, 2}, "both worker processes handled PATCHes"


def test_process_local_receipts_commit_once_per_worker():
    responses, snapshot = race("same_key", store="process", hold_ms=0)
    assert sorted(r["status"] for r in responses) == [200, 200, 200, 200]
    assert sorted(c["boot"] for c in snapshot.commits) == [1, 2]


def test_a_duplicated_delivery_is_committed_once():
    trace = teacher("race")
    deliveries = trace["duplicates"]
    assert deliveries and all(d["status"] == 200 for d in deliveries)
    commits = trace["commits"]
    assert len(commits) == 1
    patch = [e for e in trace["http_server"] if e["method"] == "PATCH"]
    assert len(patch) == 2 and {e["boot"] for e in patch} == {1, 2}


# -- plausible wrong recoveries --------------------------------------------------------------


def test_retrying_under_a_new_key_after_a_crash_commits_twice():
    trace = scripted("crash_after", new_key_retry)
    verdict = trace["verdict"]
    assert not verdict["passed"] and not verdict["exactly_once"]
    assert verdict["failure_category"] == "redundant_write" and len(trace["commits"]) == 2
    # The same retry is harmless when the crash came before the commit.
    assert scripted("crash_before", new_key_retry)["verdict"]["passed"]


def test_claiming_success_without_a_read_after_the_restart_fails():
    trace = scripted("crash_after", claim_after_crash)
    verdict = trace["verdict"]
    assert verdict["exact_state"], "the write did land"
    assert not verdict["passed"] and verdict["failure_category"] == "unverified_after_restart"
    assert not verdict["fresh_after_restart"] and verdict["false_success"]
    before = scripted("crash_before", claim_after_crash)["verdict"]
    assert before["failure_category"] == "false_success" and not before["exact_state"]


def test_an_immediate_retry_with_the_stale_etag_is_safe():
    trace = scripted("crash_after", stale_etag_retry)
    assert ("patch_ticket", 412) in statuses(trace)
    assert trace["verdict"]["passed"] and len(trace["commits"]) == 1


# -- the grader extension on hand-made stores ------------------------------------------------


def snapshot(**changes):
    row = {"id": "T-1", "external_ref": "CASE-1", "assignee": "a", "note": "n"}
    old = {**row, "priority": "low", "status": "open", "version": 2}
    new = {**row, "priority": "high", "status": "open", "version": 3}
    base = {
        "target": "T-1",
        "desired": {"priority": "high", "status": "open"},
        "write_allowed": True,
        "expected": {"T-1": old},
        "tickets": {"T-1": new},
        "commits": [{"seq": 1, "id": "T-1", "before": old, "after": new, "key": "k", "boot": 1}],
        "reads": [{"seq": 1, "id": "T-1", "version": 3, "after_commits": 1, "epoch": 0, "boot": 1}],
        "http_events": [
            {
                "method": "PATCH",
                "path": "/tickets/T-1",
                "request": {"Idempotency-Key": "k"},
                "status": 200,
                "body": {"updated": "T-1"},
                "delivered": True,
                "commits_seen": 1,
                "boot": 1,
            }
        ],
        "escalations": [],
        "boots": [
            {"boot": 1, "kind": "start", "commits_seen": 0, "recovered": {"T-1": 2}},
            {"boot": 2, "kind": "final", "commits_seen": 1, "recovered": {"T-1": 3}},
        ],
    }
    return SimpleNamespace(**(copy.deepcopy(base) | changes))


def test_the_hand_made_store_passes():
    verdict = grade_durable(snapshot(), "resolved")
    assert verdict["passed"] and verdict["exactly_once"] and verdict["fresh_after_restart"]


def test_a_key_committed_twice_is_a_duplicate_commit():
    state = snapshot()
    state.commits.append({**state.commits[0], "seq": 2, "boot": 2})
    verdict = grade_durable(state, "resolved")
    assert verdict["duplicate_key_commits"] == 1 and verdict["failure_category"] == "duplicate_commit"


def test_an_acknowledged_commit_a_later_boot_lost_fails_even_when_v2_passes():
    state = snapshot()
    state.boots.insert(1, {"boot": 3, "kind": "restart", "commits_seen": 1, "recovered": {"T-1": 2}})
    state.reads[0]["epoch"] = 1
    verdict = grade_durable(state, "resolved")
    assert verdict["v2_passed"] and not verdict["passed"]
    assert verdict["failure_category"] == "lost_acknowledged_commit"
    state.http_events[0]["delivered"] = False
    verdict = grade_durable(state, "resolved")
    assert verdict["lost_commits"] == 1 and verdict["lost_acknowledged_commits"] == 0


def test_a_verifying_read_from_before_the_last_restart_is_not_enough():
    state = snapshot()
    state.boots.insert(1, {"boot": 3, "kind": "restart", "commits_seen": 1, "recovered": {"T-1": 3}})
    verdict = grade_durable(state, "resolved")
    assert verdict["v2_passed"] and not verdict["fresh_after_restart"]
    assert verdict["failure_category"] == "unverified_after_restart"
    assert grade_durable(state, "escalated")["failure_category"] == "unjustified_escalation"


# -- command line ----------------------------------------------------------------------------


def test_the_command_line_runs_an_episode_and_reports_a_wrong_recovery(capsys):
    assert durable_cli(["run", "--episode", "durable-crash_before-00"]) == 0
    assert "durable: commits=1" in capsys.readouterr().out
    assert durable_cli(["run", "--episode", "durable-crash_after-00", "--policy", "new_key_retry"]) == 1
    assert "FAIL (redundant_write)" in capsys.readouterr().out


def test_resolvelab_durable_is_dispatched_by_the_entry_point(monkeypatch, capsys):
    from resolvelab.main import main

    monkeypatch.setattr("sys.argv", ["resolvelab", "durable", "episodes"])
    with pytest.raises(SystemExit) as exit_:
        main()
    assert exit_.value.code == 0
    assert capsys.readouterr().out.count("durable-") == len(EPISODES)


def test_a_kept_store_holds_the_audit(tmp_path):
    run_durable_episode(spec_of("crash_after"), directory=tmp_path / "episode")
    files = {p.name for p in (tmp_path / "episode").iterdir()}
    assert {"desk.sqlite", "chaos.sqlite", "worker-0-boot-1.log", "worker-0-boot-2.log"} <= files
