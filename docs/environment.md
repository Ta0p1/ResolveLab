# CaseDesk as an environment

`resolvelab.casedesk.env.CaseDeskEnv` exposes the benchmark step by step, for custom agent
loops and RL trainers. No GPU and no extra dependency.

```python
from resolvelab.casedesk.env import CaseDeskEnv

with CaseDeskEnv(pool="train_core") as env:
    obs = env.reset(seed=0)  # or episode_id="train_core-train_plain-00"
    done = False
    while not done:
        action = policy(obs["messages"])  # {"name": ..., "arguments": {...}} or JSON text
        obs, reward, done, info = env.step(action)
    print(reward, info["verdict"]["failure_category"])
```

| Call | Returns |
|---|---|
| `reset(seed=None, episode_id=None)` | observation; by id, a seeded draw from the pool, or the pool's next episode |
| `step(action)` | `(observation, reward, done, info)` |
| `state()` | episode id, pool, faults, declared factors, step count, done, error (ground truth) |
| `close()` | releases the HTTP server; also called when an episode ends |

**Observation:** `task`, `messages` (the full conversation in the study's format: system prompt,
one-shot demonstration, task, then each action and observation), `result` (the last tool
result) and `step`. It never contains fault flags or expected state; `state()` does, and is for
trainers and logs, not prompts.

**Reward:** sparse and verifiable. 1.0 when grader v2 passes the finished episode, otherwise
0.0, paid once when `done` becomes true. `info` then carries the full verdict (unsafe writes,
redundant commits, false success, spurious escalation, fresh verification), the diagnostics
(located target, faults actually exposed) and the error (`tool_budget`, `json_error`,
`schema_error`). Shaped rewards can be built from these fields; the published results use only
pass/fail.

**Termination:** `finish`, the 24-action budget, or an action that is not a valid tool call.
Invalid actions are not repaired, exactly as in evaluation.

**Fidelity:** the environment reuses the study's service, fault injection, adapter, budget and
grader. Its tests replay published model traces (passes, failures, malformed output, budget
exhaustion) and require the same observations, verdicts, diagnostics and errors as
`runner.run_episode`.

**Pools:** `train_core` and `train_pool` for training, `dev` for selection. The registered test
pool is public; `CaseDeskEnv(pool="test")` is refused unless `allow_test=True`, and test
episodes cannot be reached from a training pool.

## What the reward looks like

`python examples/casedesk_env_loop.py` runs the scripted teacher and a random policy over the
40 development episodes: the teacher earns 1.0 on every episode (all are solvable) and the
random policy 0.0, usually by escalating without a denial. The reward is sparse enough that
exploration from scratch rarely finds it; v0.4's behaviour-cloning and DAgger adapters are the
natural warm start before any RL.

## OpenEnv

[OpenEnv](https://github.com/meta-pytorch/openenv) standardises environments as servers with
`reset()`, `step()` and `state`, reward and `done` on the observation, deployable to Hugging
Face Spaces and usable from TRL. `CaseDeskEnv` maps onto that interface one to one; a packaged
OpenEnv server is planned and needs the `openenv` package to validate.
