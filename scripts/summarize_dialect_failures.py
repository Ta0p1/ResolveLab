"""Classify every failed test episode of the dialect study from its trace (exploratory).

Writes artifacts/v0.5/diagnostics/failure-causes.{json,md}. This taxonomy is diagnostic, written
after the results were seen; it is not part of the registered analysis and changes no verdict.
Causes are mutually exclusive and checked in the order of ``CAUSES``.
"""

import argparse
import json
import zipfile
from collections import Counter
from pathlib import Path

from resolvelab.casedesk.world import WorldState
from resolvelab.dialects.assignment import dialect_named
from resolvelab.dialects.spec import CANONICAL
from resolvelab.evaluation import write_report

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts/v0.5"
OUT = BUNDLE / "diagnostics"
SEEDS = (3407, 42, 2026)
RUNS = (
    ("test", "bc"),
    ("test", "bc-volume"),
    ("test", "dagger"),
    ("test", "bc-multi"),
    ("test", "bc-volume-multi"),
    ("test", "dagger-multi"),
    ("study-contract", "bc-multi"),
    ("study-contract", "bc-volume-multi"),
    ("study-contract", "dagger-multi"),
)
CAUSES = (
    "token runs to output cap",
    "malformed-token loop",
    "other invalid output",
    "repeated-write loop",
    "other budget loop",
    "wrong-record write",
    "wrong-value write",
    "claims success, no write attempted",
    "claims success after a refused write",
    "escalation error",
    "other",
)


def malformed(token):
    """The canonical form of a token every style translates to; a mangled one passes through."""
    token = str(token)
    return not (token.startswith('"v') and token.endswith('"') and token[2:-1].isdigit())


def cause(row, trace):
    """One cause per failed episode, from the row and its trace."""
    dialect = CANONICAL if row["dialect"] == CANONICAL.name else dialect_named(row["dialect"])
    patches = [o for o in trace["observations"] if o["name"] == "patch_ticket"]
    if row["error"] in ("json_error", "schema_error"):
        raw = [d for d in trace["decisions"] if "error" in d][-1]["usage"].get("raw_output", "")
        copying = row["error"] == "json_error" and f'"{dialect.args["etag"]}"' in raw
        return "token runs to output cap" if copying else "other invalid output"
    if row["error"] == "tool_budget":
        if any(malformed(o["arguments"]["etag"]) for o in patches):
            return "malformed-token loop"
        return "repeated-write loop" if trace["commits"] else "other budget loop"
    if row["unsafe_mutations"]:
        world = WorldState(trace["spec"])
        return (
            "wrong-record write"
            if any(c["id"] != world.target for c in trace["commits"])
            else "wrong-value write"
        )
    if row["failure_category"] == "false_success":
        return (
            "claims success after a refused write" if patches else "claims success, no write attempted"
        )
    if row["failure_category"] in ("spurious_escalation", "unjustified_escalation"):
        return "escalation error"
    return "other"


def summarize(bundle=BUNDLE):
    """Failure causes per run, pooled over seeds, and how often each arm reached a commit."""
    runs = {}
    for pool, arm in RUNS:
        causes = Counter()
        committed = unsafe = episodes = 0
        for seed in SEEDS:
            name = f"{arm}-{seed}"
            report = json.loads((bundle / pool / f"{name}.json").read_text(encoding="utf-8"))
            traces = zipfile.ZipFile(bundle / "traces" / pool / f"{name}.zip")
            for row in report["rows"]:
                trace = json.loads(traces.read(row["trace"]))
                episodes += 1
                committed += bool(trace["commits"])
                unsafe += bool(row["unsafe_mutations"])
                if not row["passed"]:
                    causes[cause(row, trace)] += 1
        runs[f"{pool}/{arm}"] = {
            "episodes": episodes,
            "failures": sum(causes.values()),
            "causes": {c: causes[c] for c in CAUSES},
            "episodes_with_a_commit": committed,
            "episodes_with_an_unsafe_write": unsafe,
        }
    return runs


def markdown(runs):
    lines = [
        "# Failure causes (exploratory)",
        "",
        "Every failed episode, three seeds pooled, one cause each. Written after the results were",
        "seen; not part of the registered analysis. `scripts/summarize_dialect_failures.py`.",
        "",
        "| Cause | " + " | ".join(f"`{name}`" for name in runs) + " |",
        "|---|" + "---:|" * len(runs),
    ]
    for name in CAUSES:
        counts = [str(run["causes"][name]) for run in runs.values()]
        lines.append(f"| {name} | " + " | ".join(counts) + " |")
    for label, key in (
        ("**Failures**", "failures"),
        ("Episodes with a commit", "episodes_with_a_commit"),
        ("Episodes with an unsafe write", "episodes_with_an_unsafe_write"),
    ):
        lines.append(f"| {label} | " + " | ".join(str(run[key]) for run in runs.values()) + " |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=BUNDLE)
    args = parser.parse_args()
    runs = summarize(args.bundle)
    write_report(args.bundle / "diagnostics/failure-causes.json", runs)
    (args.bundle / "diagnostics/failure-causes.md").write_text(
        markdown(runs), encoding="utf-8", newline="\n"
    )
    print(markdown(runs))


if __name__ == "__main__":
    main()
