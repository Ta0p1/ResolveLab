"""Registered CaseDesk v2 design: explicit episode specs, generated once and committed.

Every episode owns an independent record seed and reference, so episodes (not templates)
are the sampling unit for record generalization. Fault compositions are the v0.3 ones:
single mechanisms in train, disjoint pairs/triples in dev and test. Target slots are
stratified (a quarter of every pool in slot 0), task wording and injection text are
split-disjoint where declared, and test holds out two phrasing families entirely.
"""

import json
import random
from pathlib import Path

from ..benchmark import digest
from ..httpdesk.benchmark import FAULTS
from ..httpdesk.benchmark import load_manifest as load_v03_manifest
from ..httpdesk.service import DeskState
from .world import INJECTIONS, PHRASINGS, WorldState

SCHEMA = "resolvelab-casedesk-v2"
V03_MANIFEST = Path(__file__).resolve().parents[3] / "benchmarks/httpdesk-v1.json"

COMPOSITIONS = {
    "train": [
        ("train_plain", []),
        ("train_conflict", ["conflict"]),
        ("train_lost", ["lost_ack"]),
        ("train_rate", ["rate_limit"]),
        ("train_revoke", ["revoke"]),
        ("train_injection", ["injection"]),
        ("train_noop", ["already_done"]),
        ("train_concurrent", ["concurrent_resolve"]),
    ],
    "dev": [
        ("dev_conflict_injection", ["conflict", "injection"]),
        ("dev_rate_injection", ["rate_limit", "injection"]),
        ("dev_revoke_lost", ["revoke", "lost_ack"]),
        ("dev_noop_rate", ["already_done", "rate_limit"]),
    ],
    "test": [
        ("test_conflict_lost", ["conflict", "lost_ack"]),
        ("test_conflict_rate", ["conflict", "rate_limit"]),
        ("test_rate_lost", ["rate_limit", "lost_ack"]),
        ("test_conflict_rate_lost", ["conflict", "rate_limit", "lost_ack"]),
        ("test_revoke_injection", ["revoke", "injection"]),
        ("test_rate_revoke", ["rate_limit", "revoke"]),
        ("test_noop_injection", ["already_done", "injection"]),
        ("test_concurrent_rate", ["concurrent_resolve", "rate_limit"]),
        ("test_concurrent_injection", ["concurrent_resolve", "injection"]),
        ("test_lost_injection", ["lost_ack", "injection"]),
    ],
}

# Pool -> (split, records per composition). train_pool is the learner-rollout pool for
# DAgger and, for the data-volume control, the extra expert episodes.
POOLS = {
    "train_core": ("train", 8),
    "train_pool": ("train", 8),
    "dev": ("dev", 10),
    "test": ("test", 12),
}
SEEN_PHRASINGS = ["f0", "f1", "f2", "f3"]
UNSEEN_PHRASINGS = ["f4", "f5"]
POOL_INJECTIONS = {
    "train_core": ["i0", "i1", "i2"],
    "train_pool": ["i0", "i1", "i2"],
    "dev": ["i3"],
    "test": ["i4", "i5"],
}


def slot_plan(rng, count):
    """A quarter in slot 0, a quarter in slot 1 (both on page one), half on later pages."""
    quarter = count // 4
    plan = ["0"] * quarter + ["1"] * quarter + ["later"] * (count - 2 * quarter)
    rng.shuffle(plan)
    return plan


def v03_identifiers():
    manifest = load_v03_manifest(V03_MANIFEST)
    refs, ids = set(), set()
    for part in manifest["splits"].values():
        for seed in part["seeds"]:
            state = DeskState([], seed)
            refs.add(state.reference)
            ids |= set(state.tickets)
    return refs, ids


def build_manifest(master_seed=20261022):
    rng = random.Random(master_seed)
    refs, ids_v03 = v03_identifiers()
    split_ids = {"train": set(ids_v03), "dev": set(ids_v03), "test": set(ids_v03)}
    seeds = set()
    episodes = {}
    for pool, (split, per) in POOLS.items():
        rows = []
        for composition, faults in COMPOSITIONS[split]:
            slots = slot_plan(rng, per)
            groups = ["seen"] * per
            if pool == "test":
                groups = ["seen"] * (per // 2) + ["unseen"] * (per - per // 2)
                rng.shuffle(groups)
            for index, (slot, group) in enumerate(zip(slots, groups)):
                if slot == "later":
                    count = rng.randint(3, 9)
                    target = rng.randrange(2, count)
                else:
                    count, target = rng.randint(3, 9), int(slot)
                phrasing = rng.choice(SEEN_PHRASINGS if group == "seen" else UNSEEN_PHRASINGS)
                spec = {
                    "id": f"{pool}-{composition}-{index:02d}",
                    "pool": pool,
                    "composition": composition,
                    "faults": faults,
                    "n_records": count,
                    "target_pos": target,
                    "phrasing": phrasing,
                    "phrasing_group": group,
                    "injection": rng.choice(POOL_INJECTIONS[pool]) if "injection" in faults else None,
                }
                others = {s: v for s, v in split_ids.items() if s != split}
                while True:
                    seed = rng.randrange(10**8, 10**9)
                    state = WorldState({**spec, "record_seed": seed})
                    keys = set(state.tickets)
                    if (
                        seed not in seeds
                        and state.reference not in refs
                        and not any(keys & v for v in others.values())
                    ):
                        break
                seeds.add(seed)
                refs.add(state.reference)
                split_ids[split] |= keys
                rows.append({**spec, "record_seed": seed})
        episodes[pool] = rows
    return {
        "schema": SCHEMA,
        "name": "CaseDesk v2: independent-record composition benchmark",
        "master_seed": master_seed,
        "compositions": {s: [{"id": i, "faults": f} for i, f in c] for s, c in COMPOSITIONS.items()},
        "pools": {p: {"split": s, "per_composition": n} for p, (s, n) in POOLS.items()},
        "phrasings": {"seen": SEEN_PHRASINGS, "unseen_test_only": UNSEEN_PHRASINGS},
        "injections": POOL_INJECTIONS,
        "episodes": episodes,
    }


def load_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Unsupported CaseDesk v2 manifest")
    signatures = {}
    for split, rows in manifest["compositions"].items():
        for row in rows:
            faults = set(row["faults"])
            if not faults <= FAULTS or {"conflict", "concurrent_resolve"} <= faults:
                raise ValueError("Unknown or ambiguous fault composition")
            key = tuple(sorted(faults))
            if key in signatures and signatures[key] != split:
                raise ValueError("Composition shared across splits")
            signatures[key] = split
    seen_seeds, seen_ids = set(), set()
    for pool, rows in manifest["episodes"].items():
        split = manifest["pools"][pool]["split"]
        allowed = {r["id"]: r["faults"] for r in manifest["compositions"][split]}
        for spec in rows:
            if spec["pool"] != pool or allowed.get(spec["composition"]) != spec["faults"]:
                raise ValueError("Episode outside its split's compositions")
            if spec["record_seed"] in seen_seeds or spec["id"] in seen_ids:
                raise ValueError("Duplicate episode or record seed")
            if spec["phrasing"] not in PHRASINGS:
                raise ValueError("Unknown phrasing")
            if spec["phrasing"] in UNSEEN_PHRASINGS and pool != "test":
                raise ValueError("Held-out phrasing outside test")
            if ("injection" in spec["faults"]) != (spec["injection"] is not None):
                raise ValueError("Injection text without injection fault")
            if spec["injection"] and spec["injection"] not in INJECTIONS:
                raise ValueError("Unknown injection")
            seen_seeds.add(spec["record_seed"])
            seen_ids.add(spec["id"])
    return manifest


def episodes(manifest, pool):
    return list(manifest["episodes"][pool])


def manifest_digest(manifest):
    return digest(manifest)
