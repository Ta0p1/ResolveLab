"""Which dialect each registered CaseDesk v2 episode is rendered in.

Every episode gets its own dialect. Training pools draw from ``train`` dialects, dev from
``train`` dialects with seeds no training episode uses (unseen combinations of seen words),
and test from ``heldout`` dialects, so no model meets a held-out word before the test lock.
Seeds are shuffled within each pool so conventions are not aligned with manifest order.
"""

import json
import random
from dataclasses import asdict
from pathlib import Path

from ..benchmark import digest
from .spec import generate

SCHEMA = "resolvelab-casedesk-dialects-v1"
MASTER_SEED = 20261030
# pool -> (dialect split, first seed); seed ranges never overlap within a split.
POOL_SEEDS = {
    "train_core": ("train", 0),
    "train_pool": ("train", 1000),
    "dev": ("train", 2000),
    "test": ("heldout", 0),
}


def dialect_named(name):
    split, seed = name.rsplit("-", 1)
    return generate(int(seed), split)


def build_assignment(manifest, master_seed=MASTER_SEED):
    rng = random.Random(master_seed)
    episodes = {}
    for pool, (split, first) in POOL_SEEDS.items():
        specs = manifest["episodes"][pool]
        seeds = list(range(first, first + len(specs)))
        rng.shuffle(seeds)
        for spec, seed in zip(specs, seeds):
            episodes[spec["id"]] = f"{split}-{seed}"
    return {
        "schema": SCHEMA,
        "master_seed": master_seed,
        "manifest_sha256": digest(manifest),
        "pool_seeds": {pool: list(value) for pool, value in POOL_SEEDS.items()},
        "episodes": episodes,
        # Pins the generated dialects themselves, so a later edit to a word pool is detected.
        "dialects_sha256": digest(
            {name: _plain(dialect_named(name)) for name in sorted(episodes.values())}
        ),
    }


def load_assignment(path, manifest):
    assignment = json.loads(Path(path).read_text(encoding="utf-8"))
    if assignment.get("schema") != SCHEMA or assignment["manifest_sha256"] != digest(manifest):
        raise ValueError("Assignment does not belong to this manifest")
    if assignment != build_assignment(manifest, assignment["master_seed"]):
        raise ValueError("Assignment is not reproducible from the current dialect generator")
    return assignment


def _plain(dialect):
    value = asdict(dialect)
    value["codes"] = {str(k): v for k, v in value["codes"].items()}
    return value
