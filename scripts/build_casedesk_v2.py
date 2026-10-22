"""Generate the registered CaseDesk v2 manifest. Refuses to overwrite a different registration."""

import json
from pathlib import Path

from resolvelab.casedesk.manifest import build_manifest, load_manifest

PATH = Path(__file__).resolve().parents[1] / "benchmarks/casedesk-v2.json"

manifest = build_manifest()
if PATH.exists() and load_manifest(PATH) != manifest:
    raise SystemExit("A different v2 manifest is already registered; use a new name")
PATH.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
load_manifest(PATH)
print(PATH, {pool: len(rows) for pool, rows in manifest["episodes"].items()})
