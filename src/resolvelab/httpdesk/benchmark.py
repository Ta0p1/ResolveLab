"""Split validation and source provenance for the second service."""

import hashlib
import json
from pathlib import Path

from ..benchmark import digest

FAULTS = {
    "conflict",
    "lost_ack",
    "rate_limit",
    "revoke",
    "injection",
    "already_done",
    "concurrent_resolve",
}


def load_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("schema") != "resolvelab-httpdesk-v1":
        raise ValueError("Unsupported HTTP benchmark")
    seen_ids, seen_seeds, signatures = set(), set(), set()
    for split in ("train", "dev", "test"):
        section = manifest["splits"][split]
        seeds = set(section["seeds"])
        if (
            not seeds
            or not section["templates"]
            or seeds & seen_seeds
            or len(seeds) != len(section["seeds"])
        ):
            raise ValueError("Empty or overlapping split")
        seen_seeds |= seeds
        for template in section["templates"]:
            faults = set(template["faults"])
            signature = tuple(sorted(faults))
            if not faults <= FAULTS or len(faults) != len(template["faults"]):
                raise ValueError("Unknown or duplicate fault")
            if {"conflict", "concurrent_resolve"} <= faults:
                raise ValueError("Ambiguous concurrent writer")
            if template["id"] in seen_ids or signature in signatures:
                raise ValueError("Overlapping template or composition")
            seen_ids.add(template["id"])
            signatures.add(signature)
    return manifest


def cases(manifest, split):
    for template in manifest["splits"][split]["templates"]:
        for seed in manifest["splits"][split]["seeds"]:
            yield template, seed


def validate_rows(rows, manifest, split):
    if split not in {"train", "dev"}:
        raise ValueError("Test data cannot be used for training")
    allowed = {(t["id"], seed) for t, seed in cases(manifest, split)}
    seen = set()
    for row in rows:
        identity = (row["template"], row["seed"], row["step"])
        if row["split"] != split or row["manifest_sha256"] != digest(manifest):
            raise ValueError("Wrong split or manifest")
        if identity[:2] not in allowed or identity in seen or not row["verified_teacher"]:
            raise ValueError("Invalid training provenance")
        seen.add(identity)
    if not rows:
        raise ValueError("Empty training data")


def source_hash():
    root = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    for path in sorted([*root.rglob("*.py"), root / "httpdesk" / "demo.json"]):
        h.update(path.relative_to(root).as_posix().encode())
        h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()
