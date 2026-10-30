"""The step-wise environment must behave exactly like the evaluation loop."""

import json
import zipfile
from pathlib import Path

import pytest

from resolvelab.casedesk.env import CaseDeskEnv
from resolvelab.casedesk.manifest import load_manifest
from resolvelab.casedesk.runner import actions_of, run_episode

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = load_manifest(ROOT / "benchmarks/casedesk-v2.json")
BUNDLE = ROOT / "artifacts/v0.4"


def play(env, episode_id, actions):
    obs = env.reset(episode_id=episode_id)
    reward, done, info = 0.0, False, {}
    for action in actions:
        obs, reward, done, info = env.step(action)
        if done:
            break
    return obs, reward, done, info


@pytest.mark.parametrize("pool", ["train_core", "dev"])
def test_teacher_actions_earn_reward_one_with_the_evaluation_verdict(pool):
    with CaseDeskEnv(pool=pool, manifest=MANIFEST) as env:
        for spec in MANIFEST["episodes"][pool][::4]:
            reference = run_episode(spec)
            _, reward, done, info = play(env, spec["id"], actions_of(reference))
            assert done and reward == 1.0
            assert info["verdict"] == reference["verdict"]
            assert info["diagnostics"] == reference["diagnostics"]


@pytest.mark.parametrize("arm", ["bc-volume-2026", "dagger-2026"])
def test_published_model_traces_replay_to_the_same_verdicts(arm):
    report = json.loads((BUNDLE / "test" / f"{arm}.json").read_text(encoding="utf-8"))
    traces = zipfile.ZipFile(BUNDLE / "traces/test" / f"{arm}.zip")
    with CaseDeskEnv(pool="test", manifest=MANIFEST, allow_test=True) as env:
        for row in report["rows"][::3]:
            trace = json.loads(traces.read(row["trace"]))
            steps = [
                d["action"] if "action" in d else d["usage"].get("raw_output", "")
                for d in trace["decisions"]
            ]
            obs, reward, done, info = play(env, row["spec_id"], steps)
            assert done, row["spec_id"]
            assert info["verdict"] == trace["verdict"], row["spec_id"]
            assert info["diagnostics"] == trace["diagnostics"], row["spec_id"]
            assert info["error"] == trace["error"], row["spec_id"]
            assert reward == float(trace["verdict"]["passed"])
            assert env.observations == trace["observations"]


def test_invalid_action_ends_the_episode_without_repair():
    with CaseDeskEnv(manifest=MANIFEST) as env:
        env.reset(seed=1)
        obs, reward, done, info = env.step('{"name": "list_tickets"')
        assert done and reward == 0.0 and info["error"] == "json_error"
        assert obs["step"] == 0 and not info["verdict"]["passed"]
        with pytest.raises(RuntimeError):
            env.step({"name": "list_tickets", "arguments": {"cursor": ""}})
        env.reset(seed=1)
        _, _, done, info = env.step({"name": "wait", "arguments": {"ticket_id": "T-1"}})
        assert done and info["error"] == "schema_error"


def test_budget_exhaustion_ends_the_episode():
    with CaseDeskEnv(manifest=MANIFEST, max_tools=3) as env:
        env.reset(seed=2)
        results = [env.step({"name": "list_tickets", "arguments": {"cursor": ""}}) for _ in range(3)]
        assert [r[2] for r in results] == [False, False, True]
        assert results[-1][1] == 0.0 and results[-1][3]["error"] == "tool_budget"


def test_observations_carry_no_ground_truth():
    with CaseDeskEnv(manifest=MANIFEST) as env:
        obs = env.reset(episode_id="train_core-train_conflict-00")
        assert set(obs) == {"task", "messages", "result", "step"}
        obs, *_ = env.step({"name": "list_tickets", "arguments": {"cursor": ""}})
        assert set(obs) == {"task", "messages", "result", "step"}
        assert obs["messages"][-1]["role"] == "user" and obs["result"]["status"] == 200
        assert env.state()["faults"] == ["conflict"]


def test_test_pool_is_opt_in():
    with pytest.raises(ValueError):
        CaseDeskEnv(pool="test", manifest=MANIFEST)
    with CaseDeskEnv(manifest=MANIFEST) as env, pytest.raises(ValueError):
        env.reset(episode_id=MANIFEST["episodes"]["test"][0]["id"])


def test_reset_is_reproducible_and_cycles():
    with CaseDeskEnv(pool="dev", manifest=MANIFEST) as env:
        first = env.reset(seed=7)["task"]
        assert env.reset(seed=7)["task"] == first
        ids = []
        for _ in range(3):
            env.reset()
            ids.append(env.state()["episode_id"])
        assert ids == [s["id"] for s in MANIFEST["episodes"]["dev"][:3]]


def test_server_is_released_after_each_episode():
    env = CaseDeskEnv(manifest=MANIFEST)
    env.reset(seed=3)
    assert env._server is not None
    env.step({"name": "finish", "arguments": {"outcome": "resolved"}})
    assert env._server is None and env.state()["done"]
