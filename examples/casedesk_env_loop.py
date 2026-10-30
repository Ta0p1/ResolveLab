"""CaseDesk as an environment: the reward signal an RL trainer would see, no GPU needed.

Runs two policies over the development pool through ``CaseDeskEnv`` and prints their mean
reward: the scripted teacher (an upper bound; every episode is solvable) and a random policy
that picks a tool and fills its arguments from what it has seen. Replace ``random_policy``
with a model call on ``obs["messages"]`` to collect rollouts for your own trainer.

    python examples/casedesk_env_loop.py
"""

import random
import statistics

from resolvelab.casedesk.env import CaseDeskEnv
from resolvelab.casedesk.teacher import teacher_next


def teacher_policy(obs, env):
    return teacher_next(obs["task"], env.observations).model_dump()


def random_policy(obs, env, rng=random.Random(0)):
    seen = [o["result"] for o in env.observations if o["result"].get("status") == 200]
    ids = [t["id"] for r in seen for t in r.get("body", {}).get("tickets", [])] or ["T-0000-0"]
    etags = [r["etag"] for r in seen if "etag" in r] or ['"v1"']
    name = rng.choice(["list_tickets", "get_ticket", "patch_ticket", "wait", "escalate", "finish"])
    arguments = {
        "list_tickets": {"cursor": rng.choice(["", "page-2"])},
        "get_ticket": {"ticket_id": rng.choice(ids)},
        "patch_ticket": {
            "ticket_id": rng.choice(ids),
            "etag": rng.choice(etags),
            "priority": rng.choice(["low", "normal", "high", "urgent"]),
            "status": rng.choice(["open", "pending", "resolved"]),
            "idempotency_key": f"k{rng.randrange(1000)}",
        },
        "wait": {"seconds": rng.randint(1, 5)},
        "escalate": {"reason": "random"},
        "finish": {"outcome": rng.choice(["resolved", "escalated"])},
    }[name]
    return {"name": name, "arguments": arguments}


def rollout(env, policy):
    obs, done, reward, steps = env.reset(), False, 0.0, 0
    while not done:
        obs, reward, done, info = env.step(policy(obs, env))
        steps += 1
    return reward, steps, info["verdict"]["failure_category"]


def main():
    with CaseDeskEnv(pool="dev") as env:
        for name, policy in (("teacher", teacher_policy), ("random", random_policy)):
            results = [rollout(env, policy) for _ in range(len(env.specs))]
            rewards = [r for r, _, _ in results]
            failures = statistics.multimode([c for _, _, c in results if c]) if 0 in rewards else []
            print(
                f"{name:8} mean reward {statistics.mean(rewards):.3f} over {len(rewards)} dev episodes, "
                f"mean steps {statistics.mean(s for _, s, _ in results):.1f}"
                + (f", most common failure: {failures[0]}" if failures else "")
            )


if __name__ == "__main__":
    main()
