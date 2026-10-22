"""Tabulate the v0.3 position counterfactual (exploratory; see diagnose_v03_position.py)."""

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".local/v04/diag-position"
OUT = ROOT / "artifacts/v0.4/diagnostics/position-summary"
ARMS = ["base-0.6b", "base-1.7b", "lora-3407", "lora-42", "lora-2026"]


def bucket(slot):
    return "slot 0" if slot == 0 else "slot 1" if slot == 1 else "slot 2+ (page 2+)"


def main():
    table, failures = (
        collections.defaultdict(lambda: [0, 0]),
        collections.defaultdict(collections.Counter),
    )
    for arm in ARMS:
        report = json.loads((SOURCE / f"{arm}.json").read_text(encoding="utf-8"))
        for row in report["rows"]:
            key = (arm, row["prompt"], bucket(row["slot"]))
            table[key][0] += row["passed"]
            table[key][1] += 1
            if not row["passed"]:
                failures[(arm, row["prompt"])][row["failure"]] += 1
    lines = [
        "| Arm | Demo target slot | Target slot 0 | Target slot 1 | Target slot 2+ |",
        "|---|---|---:|---:|---:|",
    ]
    for arm in ARMS:
        for prompt, label in (
            ("demo_slot3", "3 (published prompt)"),
            ("demo_slot0", "0 (counterfactual)"),
        ):
            cells = [table[(arm, prompt, b)] for b in ("slot 0", "slot 1", "slot 2+ (page 2+)")]
            lines.append(f"| {arm} | {label} | " + " | ".join(f"{p}/{n}" for p, n in cells) + " |")
    result = {
        "cells": {" / ".join(k): {"passed": v[0], "episodes": v[1]} for k, v in sorted(table.items())},
        "failure_categories": {" / ".join(k): dict(v) for k, v in sorted(failures.items())},
        "design": "v0.3 test records 6301/6302/6303 x every target slot x {plain, conflict+lost_ack} x "
        "{published demo (target slot 3), same demo episode with target moved to slot 0}; record "
        "contents and IDs fixed, only order changes. Exploratory diagnosis of a published failure.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.with_suffix(".json").write_text(
        json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    OUT.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    for key, counts in sorted(failures.items()):
        print(key, dict(counts))


if __name__ == "__main__":
    main()
