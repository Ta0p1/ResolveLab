"""Imitation rows in dialects: the v0.4 row builders with dialect conversations and targets.

A row's messages are the dialect conversation the policy saw and its target is the dialect
action, so ``training.train`` (which only needs ``target_text`` to parse to ``target``) trains
on dialect text unchanged. States, labels and verification are v0.4's: a DAgger label comes
from ``casedesk.runner.label_state`` on the canonical form of the learner's prefix and is kept
only if the teacher, continuing from exactly that state, passes grader v2.
"""

from ..benchmark import digest
from ..casedesk.data import TRAINING_POOLS
from ..casedesk.data import validate_rows as validate_study_rows
from ..casedesk.runner import actions_of, label_state
from .assignment import dialect_named
from .runner import dialect_actions, run_dialect_episode
from .translate import Translator


def _check(manifest, assignment):
    if assignment["manifest_sha256"] != digest(manifest):
        raise ValueError("Assignment does not belong to this manifest")


def row(spec, manifest, assignment, step, messages, target, origin, **extra):
    name = assignment["episodes"][spec["id"]]
    translator = Translator(dialect_named(name), seed=spec["id"])
    return {
        "messages": messages,
        "target": target,
        "target_text": translator.action_text(target),
        "step": step,
        "spec_id": spec["id"],
        "pool": spec["pool"],
        "composition": spec["composition"],
        "dialect": name,
        "origin": origin,
        "verified_teacher": True,
        "manifest_sha256": digest(manifest),
        "assignment_sha256": digest(assignment),
        **extra,
    }


def expert_rows(manifest, assignment, pool, limit=None):
    _check(manifest, assignment)
    if pool not in TRAINING_POOLS["train"] | TRAINING_POOLS["dev"]:
        raise ValueError("Only train/dev pools may be collected")
    rows, episodes = [], []
    for spec in manifest["episodes"][pool][:limit]:
        dialect = dialect_named(assignment["episodes"][spec["id"]])
        trace = run_dialect_episode(spec, dialect, keep_messages=True)
        if not trace["verdict"]["passed"]:
            raise ValueError(f"Teacher failed {spec['id']} in {dialect.name}: {trace['verdict']}")
        for step, written in zip(trace["steps"], dialect_actions(trace)):
            rows.append(
                row(spec, manifest, assignment, step["step"], step["messages"], written, "expert")
            )
        episodes.append({"spec_id": spec["id"], "dialect": dialect.name, "actions": len(trace["steps"])})
    return rows, episodes


def dagger_rows(manifest, assignment, pool, policy, rollout, limit=None):
    """One learner rollout per spec in its dialect; every visited state labelled and verified."""
    _check(manifest, assignment)
    if pool not in TRAINING_POOLS["train"]:
        raise ValueError("DAgger states come from training pools only")
    rows, episodes = [], []
    for spec in manifest["episodes"][pool][:limit]:
        dialect = dialect_named(assignment["episodes"][spec["id"]])
        translator = Translator(dialect, seed=spec["id"])
        trace = run_dialect_episode(spec, dialect, policy, keep_messages=True)
        canonical, written = actions_of(trace), dialect_actions(trace)
        kept = dropped = agreed = 0
        for t, step in enumerate(trace["steps"]):
            label, verified, _ = label_state(spec, canonical[:t])
            if label is None or not verified:
                dropped += 1
                continue
            agree = label == canonical[t]
            agreed += agree
            kept += 1
            target = translator.from_canonical(label)
            rows.append(
                row(
                    spec,
                    manifest,
                    assignment,
                    t,
                    step["messages"],
                    target,
                    "dagger",
                    rollout=rollout,
                    learner_action=written[t],
                    learner_agreed=agree,
                )
            )
        episodes.append(
            {
                "spec_id": spec["id"],
                "dialect": dialect.name,
                "rollout": rollout,
                "learner_passed": trace["verdict"]["passed"],
                "learner_failure": trace["verdict"]["failure_category"],
                "learner_error": trace["error"],
                "learner_actions": len(canonical),
                "labelled": kept,
                "dropped_unrecoverable": dropped,
                "learner_agreed": agreed,
            }
        )
    return rows, episodes


def validate_rows(rows, manifest, split, assignment):
    """v0.4 provenance checks, plus: every row is in its episode's assigned train dialect."""
    validate_study_rows(rows, manifest, split)
    _check(manifest, assignment)
    for item in rows:
        name = assignment["episodes"].get(item["spec_id"])
        if item.get("dialect") != name or not name.startswith("train-"):
            raise ValueError("Row is not in its episode's assigned training dialect")
        if item["assignment_sha256"] != digest(assignment):
            raise ValueError("Row was built from a different assignment")
