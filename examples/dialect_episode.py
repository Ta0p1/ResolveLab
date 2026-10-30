"""One CaseDesk episode in a held-out API dialect, next to the same episode in the study's API.

The dialect renames every tool, argument, field, value and error, and changes the
concurrency token, pagination, status codes and time unit. The HTTP service, its injected
faults and the grader are unchanged, so both runs must commit the same change.

    python examples/dialect_episode.py [--seed 3]
"""

import argparse
import json
from pathlib import Path

from resolvelab.casedesk.manifest import load_manifest
from resolvelab.casedesk.runner import run_episode
from resolvelab.dialects import Translator, dialect_actions, generate, run_dialect_episode

ROOT = Path(__file__).resolve().parents[1]
EPISODE = "test-test_conflict_rate-07"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=3)
    seed = parser.parse_args().seed
    manifest = load_manifest(ROOT / "benchmarks/casedesk-v2.json")
    spec = next(s for s in manifest["episodes"]["test"] if s["id"] == EPISODE)
    dialect = generate(seed, "heldout")
    print(f"Episode {spec['id']} (faults {spec['faults']}) in dialect {dialect.name}:")
    print(f"  token {dialect.token}, pagination {dialect.cursor}, waits in {dialect.unit}")
    print(f"  conflict -> {dialect.codes[412]}, rate limit -> {dialect.codes[429]}\n")

    canonical = run_episode(spec)
    trace = run_dialect_episode(spec, dialect)
    translator = Translator(dialect, seed=spec["id"])
    print("  Task:", trace["dialect_task"], "\n")
    print("  Scripted teacher, as the agent sees the dialect:")
    for written, obs in zip(dialect_actions(trace), trace["observations"]):
        shown = translator.observe(obs["name"], obs["result"])
        print(f"    {json.dumps(written)[:84]:<86} -> {shown.get('status', '-')}")
    print()
    for name, run in (("study API", canonical), ("dialect", trace)):
        verdict = run["verdict"]
        print(f"  {name:<9}: passed={verdict['passed']}, commits={verdict['commits']}")
    same = [c["after"] for c in canonical["commits"]] == [c["after"] for c in trace["commits"]]
    assert canonical["verdict"]["passed"] and trace["verdict"]["passed"] and same
    print("  Both runs committed the same final record.")


if __name__ == "__main__":
    main()
