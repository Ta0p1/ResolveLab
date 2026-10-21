"""Versioned composition holdout. Split membership is never a policy observation."""

import hashlib
import json
from pathlib import Path

from .scenarios import Scenario
from .store import dumps

FAULTS = {"mapping", "rate", "partial", "lost", "readonly", "stale", "corrupt", "injection"}


def digest(value) -> str:
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def load_manifest(path: str | Path) -> dict:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("schema") != "resolvelab-composition-v1":
        raise ValueError("Unsupported benchmark schema")
    ids, signatures, seeds = set(), set(), set()
    for split in ("train", "dev", "test"):
        section = manifest["splits"][split]
        if not section["seeds"] or not section["templates"]:
            raise ValueError("Empty benchmark split")
        split_seeds = set(section["seeds"])
        if len(split_seeds) != len(section["seeds"]) or split_seeds & seeds:
            raise ValueError("Duplicate or overlapping seeds")
        seeds |= split_seeds
        for template in section["templates"]:
            faults = template["faults"]
            signature = tuple(sorted(faults))
            if not set(faults) <= FAULTS or len(faults) != len(set(faults)):
                raise ValueError("Unknown or duplicate fault")
            if {"partial", "lost"} <= set(faults):
                raise ValueError("Ambiguous interruption composition")
            if signature in signatures or template["id"] in ids:
                raise ValueError("Overlapping fault composition or template ID")
            signatures.add(signature)
            ids.add(template["id"])
    return manifest


def cases(manifest: dict, split: str):
    section = manifest["splits"][split]
    for template in section["templates"]:
        spec = Scenario(
            template["id"],
            template["id"],
            "Composition benchmark",
            "Advanced",
            tuple(template["faults"]),
        )
        for seed in section["seeds"]:
            yield spec, seed


def validate_training_rows(rows: list[dict], manifest: dict, split="train"):
    if split not in {"train", "dev"}:
        raise ValueError("Test episodes cannot become supervised data")
    allowed = {(s.id, seed) for s, seed in cases(manifest, split)}
    expected = digest(manifest)
    seen = set()
    for row in rows:
        if row["split"] != split or row["manifest_sha256"] != expected:
            raise ValueError("Wrong split or manifest fingerprint")
        if (row["template"], row["seed"]) not in allowed:
            raise ValueError("Episode is outside the authorized split")
        identity = (row["template"], row["seed"], row["step"])
        if identity in seen:
            raise ValueError("Duplicate training step")
        seen.add(identity)
        if not row["verified_teacher"]:
            raise ValueError("Unverified teacher trajectory")
    if not rows:
        raise ValueError("No training rows")
