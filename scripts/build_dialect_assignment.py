"""Generate the episode -> dialect assignment. Refuses to overwrite a different one."""

import json
from pathlib import Path

from resolvelab.casedesk.manifest import load_manifest
from resolvelab.dialects.assignment import build_assignment, load_assignment

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "benchmarks/casedesk-dialects-v1.json"

manifest = load_manifest(ROOT / "benchmarks/casedesk-v2.json")
assignment = build_assignment(manifest)
if PATH.exists() and json.loads(PATH.read_text(encoding="utf-8")) != assignment:
    raise SystemExit("A different dialect assignment already exists; use a new name")
PATH.write_text(json.dumps(assignment, indent=1) + "\n", encoding="utf-8", newline="\n")
load_assignment(PATH, manifest)
print(PATH, len(assignment["episodes"]), "episodes")
