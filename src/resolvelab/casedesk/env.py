"""CaseDesk as a step-wise environment for agent loops and RL trainers.

    with CaseDeskEnv(pool="train_core") as env:
        obs = env.reset(seed=0)                      # or episode_id="train_core-train_plain-00"
        done = False
        while not done:
            action = policy(obs["messages"])         # {"name": ..., "arguments": {...}}
            obs, reward, done, info = env.step(action)

Semantics match ``runner.run_episode`` (tested by replaying published traces): the same real
HTTP service, fault injection, 24-action budget and grader v2. The reward is sparse and
verifiable: 1.0 when grader v2 passes the finished episode, otherwise 0.0, paid once at the
end. An action that is not a valid tool call ends the episode with reward 0, as it does in
evaluation; nothing is repaired. Observations carry the conversation and tool results only,
never fault flags or expected state. ``state()`` exposes those for trainers and logs; keep it
out of prompts.

The registered test pool is public, so training on it is refused unless ``allow_test=True``.
"""

import copy
import json
import random

from ..httpdesk.adapter import DeskAdapter
from ..httpdesk.schema import append_observation, initial_messages, validate_action
from ..httpdesk.service import DeskServer
from .grading import diagnose, grade_v2
from .manifest import load_manifest
from .runner import MAX_TOOLS
from .world import WorldState

DEFAULT_MANIFEST = "benchmarks/casedesk-v2.json"


class CaseDeskEnv:
    def __init__(
        self,
        pool="train_core",
        manifest=None,
        *,
        max_tools=MAX_TOOLS,
        prompt=initial_messages,
        allow_test=False,
    ):
        if pool == "test" and not allow_test:
            raise ValueError("The registered test pool is public; pass allow_test=True to use it anyway")
        if manifest is None or isinstance(manifest, str):
            from pathlib import Path

            path = Path(manifest or Path(__file__).resolve().parents[3] / DEFAULT_MANIFEST)
            manifest = load_manifest(path)
        self.manifest, self.pool, self.max_tools, self.prompt = manifest, pool, max_tools, prompt
        self.specs = list(manifest["episodes"][pool])
        self.by_id = {s["id"]: s for rows in manifest["episodes"].values() for s in rows}
        self._next, self._server, self._adapter = 0, None, None
        self.spec = self.world = None
        self.messages, self.observations = [], []
        self.done, self.error = True, None

    # -- lifecycle -------------------------------------------------------------------------

    def reset(self, seed=None, episode_id=None):
        """Start an episode: by id, by a seeded draw from the pool, or the pool's next one."""
        self.close()
        if episode_id is not None:
            if episode_id not in self.by_id:
                raise ValueError(f"Unknown episode {episode_id!r}")
            spec = self.by_id[episode_id]
            if spec["pool"] == "test" and self.pool != "test":
                raise ValueError("Test episodes need CaseDeskEnv(pool='test', allow_test=True)")
        elif seed is not None:
            spec = random.Random(seed).choice(self.specs)
        else:
            spec, self._next = self.specs[self._next % len(self.specs)], self._next + 1
        self.spec, self.world = spec, WorldState(spec)
        self._server = DeskServer(self.world).__enter__()
        self._adapter = DeskAdapter(self._server.url)
        self.messages = self.prompt(self.world.task)
        self.observations, self.done, self.error = [], False, None
        return self._observation(None)

    def close(self):
        if self._adapter is not None:
            self._adapter.close()
        if self._server is not None:
            self._server.__exit__(None, None, None)
        self._server = self._adapter = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # -- stepping --------------------------------------------------------------------------

    def step(self, action):
        """Apply one tool action (dict, JSON text or validated Action)."""
        if self.done:
            raise RuntimeError("Episode is over; call reset()")
        try:
            if isinstance(action, str):
                action = json.loads(action)
            action = validate_action(action if isinstance(action, dict) else action.model_dump())
        except (ValueError, TypeError) as exc:
            self.error = "json_error" if isinstance(exc, json.JSONDecodeError) else "schema_error"
            return self._finish(None, {"invalid_action": str(exc)[:300]})
        result = self._adapter.dispatch(action)
        self.observations.append({"name": action.name, "arguments": action.arguments, "result": result})
        append_observation(self.messages, action.name, action.arguments, result)
        if action.name == "finish":
            return self._finish(action.arguments["outcome"], {})
        if len(self.observations) >= self.max_tools:
            self.error = "tool_budget"
            return self._finish(None, {})
        return self._observation(result), 0.0, False, {}

    def _finish(self, claim, extra):
        self.done = True
        verdict = grade_v2(self.world, claim)
        info = {
            "verdict": verdict,
            "diagnostics": diagnose(self.world, self.observations),
            "error": self.error,
            "episode_id": self.spec["id"],
            **extra,
        }
        result = self.observations[-1]["result"] if self.observations else None
        observation = self._observation(result)
        self.close()
        return observation, 1.0 if verdict["passed"] else 0.0, True, info

    def _observation(self, result):
        return {
            "task": self.world.task,
            "messages": copy.deepcopy(self.messages),
            "result": result,
            "step": len(self.observations),
        }

    def state(self):
        """Ground truth for trainers and logs; never show it to the policy."""
        if self.spec is None:
            return {"episode_id": None}
        return {
            "episode_id": self.spec["id"],
            "pool": self.spec["pool"],
            "faults": list(self.spec["faults"]),
            "factors": self.world.factors,
            "step_count": len(self.observations),
            "done": self.done,
            "error": self.error,
        }
