"""Imitation rows for v2: expert demonstrations and DAgger-labelled learner states.

Behaviour cloning trains only on states the expert visits, so a learner that leaves that
distribution (re-listing pages, reading a near-miss record) has never seen a correct action
from where it now is; errors compound over the horizon. DAgger (Ross, Gordon & Bagnell, 2011)
rolls out the learner, asks the expert what it would do at every visited state, and trains on
the aggregate. Here every label is additionally verified: the teacher must finish the episode
from exactly that state and pass the independent grader, otherwise the state is dropped.

All rows come from train/dev pools. Test specs can never be collected.
"""

import random

from ..benchmark import digest
from ..httpdesk.schema import action_json
from .runner import actions_of, label_state, run_episode

TRAINING_POOLS = {"train": {"train_core", "train_pool"}, "dev": {"dev"}}


def row(spec, manifest, step, messages, target, origin, **extra):
    return {
        "messages": messages,
        "target": target,
        "target_text": action_json(target),
        "step": step,
        "spec_id": spec["id"],
        "pool": spec["pool"],
        "composition": spec["composition"],
        "origin": origin,
        "verified_teacher": True,
        "manifest_sha256": digest(manifest),
        **extra,
    }


def expert_rows(manifest, pool):
    if pool not in TRAINING_POOLS["train"] | TRAINING_POOLS["dev"]:
        raise ValueError("Only train/dev pools may be collected")
    rows, episodes = [], []
    for spec in manifest["episodes"][pool]:
        trace = run_episode(spec, keep_messages=True)
        if not trace["verdict"]["passed"]:
            raise ValueError(f"Teacher failed {spec['id']}: {trace['verdict']}")
        for step, decision in zip(trace["steps"], trace["decisions"]):
            rows.append(
                row(spec, manifest, step["step"], step["messages"], decision["action"], "expert")
            )
        episodes.append({"spec_id": spec["id"], "actions": len(trace["decisions"])})
    return rows, episodes


def dagger_rows(manifest, pool, provider, rollout):
    """One learner rollout per spec; every visited state labelled by the verified teacher."""
    if pool not in TRAINING_POOLS["train"]:
        raise ValueError("DAgger states come from training pools only")
    rows, episodes = [], []
    for spec in manifest["episodes"][pool]:
        trace = run_episode(spec, provider, keep_messages=True)
        actions = actions_of(trace)
        kept = dropped = agreed = 0
        for t, step in enumerate(trace["steps"]):
            label, verified, _ = label_state(spec, actions[:t])
            if label is None or not verified:
                dropped += 1
                continue
            agree = label == actions[t]
            agreed += agree
            kept += 1
            rows.append(
                row(
                    spec,
                    manifest,
                    t,
                    step["messages"],
                    label,
                    "dagger",
                    rollout=rollout,
                    learner_action=actions[t],
                    learner_agreed=agree,
                )
            )
        episodes.append(
            {
                "spec_id": spec["id"],
                "rollout": rollout,
                "learner_passed": trace["verdict"]["passed"],
                "learner_failure": trace["verdict"]["failure_category"],
                "learner_actions": len(actions),
                "labelled": kept,
                "dropped_unrecoverable": dropped,
                "learner_agreed": agreed,
            }
        )
    return rows, episodes


def subsample(rows, count, seed):
    """Deterministic, episode-order-preserving subsample used to match dataset sizes."""
    if count > len(rows):
        raise ValueError("Cannot upsample")
    keep = set(random.Random(seed).sample(range(len(rows)), count))
    return [r for i, r in enumerate(rows) if i in keep]


def validate_rows(rows, manifest, split):
    """Provenance check passed to ``training.train``: no test rows, no duplicates, verified."""
    if split not in TRAINING_POOLS:
        raise ValueError("Test data cannot be used for training")
    pools = TRAINING_POOLS[split]
    specs = {s["id"] for p in pools for s in manifest["episodes"][p]}
    seen = set()
    for item in rows:
        identity = (item["spec_id"], item["origin"], item.get("rollout"), item["step"])
        if item["manifest_sha256"] != digest(manifest) or item["pool"] not in pools:
            raise ValueError("Wrong manifest or pool")
        if item["spec_id"] not in specs or identity in seen or not item["verified_teacher"]:
            raise ValueError("Invalid training provenance")
        seen.add(identity)
    if not rows:
        raise ValueError("Empty training data")
