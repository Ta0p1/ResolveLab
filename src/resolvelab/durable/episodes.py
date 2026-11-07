"""The ``casedesk-durable-v1`` experiment: process faults composed with the CaseDesk ones.

An engineering suite for the durable environment, generated in code from a fixed seed. It is
not a registered study and has no held-out split: nothing is trained or selected on it, and
no published result depends on it. Records come from the v2 generator (``WorldState``), with
record seeds disjoint from every registered v2 episode.

New faults (all observable by the agent as a request without a response):

- ``crash_before_commit``: the worker dies inside the first committing write, before commit.
- ``crash_after_commit``: the worker dies after that write is durable, before it responds.
- ``restart_after_commit``: every worker is killed once the first committing request has been
  answered; the next request finds the service down, then it is restarted on the same store.
- ``duplicate_delivery``: every PATCH is delivered to two workers at the same moment, as a
  retrying load balancer would; the agent sees the first worker's response.
"""

import random

from ..casedesk.manifest import SEEN_PHRASINGS, load_manifest
from ..httpdesk.benchmark import FAULTS as CASEDESK_FAULTS
from ..packaged import benchmark_file

EXPERIMENT = "casedesk-durable-v1"
MASTER_SEED = 20261107
PER_COMPOSITION = 2

CRASHES = ("crash_before_commit", "crash_after_commit")
PROCESS_FAULTS = frozenset({*CRASHES, "restart_after_commit", "duplicate_delivery"})
FAULTS = frozenset(CASEDESK_FAULTS) | PROCESS_FAULTS

# (composition, faults, workers). Every episode needs a write, so each process fault fires.
COMPOSITIONS = [
    ("crash_after", ["crash_after_commit"], 1),
    ("crash_before", ["crash_before_commit"], 1),
    ("crash_before_after", ["crash_before_commit", "crash_after_commit"], 1),
    ("restart", ["restart_after_commit"], 1),
    ("race", ["duplicate_delivery"], 2),
    ("crash_after_two_workers", ["crash_after_commit"], 2),
    ("restart_two_workers", ["restart_after_commit"], 2),
    ("crash_after_conflict", ["crash_after_commit", "conflict"], 1),
    ("crash_before_lost", ["crash_before_commit", "lost_ack"], 1),
    ("crash_before_rate", ["crash_before_commit", "rate_limit"], 1),
    ("restart_lost", ["restart_after_commit", "lost_ack"], 1),
    ("race_conflict", ["duplicate_delivery", "conflict"], 2),
    ("race_rate", ["duplicate_delivery", "rate_limit"], 2),
    ("race_revoke", ["duplicate_delivery", "revoke"], 2),
]


def validate_spec(spec):
    faults = set(spec["faults"])
    if not faults <= FAULTS or len(faults) != len(spec["faults"]):
        raise ValueError(f"Unknown or repeated fault in {sorted(spec['faults'])}")
    if {"conflict", "concurrent_resolve"} <= faults:
        raise ValueError("conflict and concurrent_resolve are ambiguous together")
    workers = spec.get("workers", 1)
    if workers not in (1, 2):
        raise ValueError("An episode runs one or two workers")
    if "duplicate_delivery" in faults and workers < 2:
        raise ValueError("duplicate_delivery needs two workers")
    if "duplicate_delivery" in faults and faults & {*CRASHES, "lost_ack"}:
        # The agent would see whichever duplicate won the race, so its trace would not replay.
        raise ValueError("duplicate_delivery is not composed with crashes or lost_ack")
    return spec


def registered_seeds():
    path = benchmark_file("casedesk-v2.json")
    if not path.exists():
        return set()
    manifest = load_manifest(path)
    return {spec["record_seed"] for rows in manifest["episodes"].values() for spec in rows}


def build_episodes(master_seed=MASTER_SEED, per_composition=PER_COMPOSITION):
    rng = random.Random(master_seed)
    taken = registered_seeds()
    rows = []
    for composition, faults, workers in COMPOSITIONS:
        for index in range(per_composition):
            count = rng.randint(3, 9)
            seed = rng.randrange(10**8, 10**9)
            while seed in taken:
                seed = rng.randrange(10**8, 10**9)
            taken.add(seed)
            rows.append(
                validate_spec(
                    {
                        "id": f"durable-{composition}-{index:02d}",
                        "pool": "durable",
                        "composition": composition,
                        "faults": list(faults),
                        "workers": workers,
                        "n_records": count,
                        "target_pos": rng.randrange(count),
                        "phrasing": rng.choice(SEEN_PHRASINGS),
                        "injection": None,
                        "record_seed": seed,
                    }
                )
            )
    return rows


def episodes_by_id():
    return {spec["id"]: spec for spec in build_episodes()}
