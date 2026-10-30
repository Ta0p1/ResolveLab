"""GPU-free audit of a dialect study bundle, in parts that can each be checked on their own.

- ``verify_inputs``: assignment, sources, prompts and grammars against the lock.
- ``verify_expert_rows``: expert data regenerates byte for byte in its dialects.
- ``verify_dagger_rows``: every DAgger label is re-derived from the learner state stored in its
  row (the dialect conversation, translated back) and re-verified by teacher continuation.
- ``verify_reports``: every evaluation trace hashes as reported and replays in its dialect over
  real HTTP to the same observations, verdict and diagnostics; summaries recompute.
"""

import hashlib
import json

from ..benchmark import digest
from ..casedesk.evaluate import summarize
from ..casedesk.runner import label_state
from ..store import dumps
from .assignment import build_assignment, dialect_named
from .data import expert_rows
from .evaluate import dialect_columns
from .lock import contract_digests, source_hash
from .prompt import initial_messages
from .runner import run_dialect_episode
from .translate import Translator


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_inputs(lock, manifest, assignment, study):
    assert assignment == build_assignment(manifest, assignment["master_seed"]), "assignment"
    assert digest(manifest) == lock["manifest_sha256"] and digest(study) == lock["study_sha256"]
    assert digest(assignment) == lock["assignment_sha256"], "assignment hash"
    assert source_hash(lock["source_files"]) == lock["source_sha256"], "locked source files changed"
    test_ids = [s["id"] for s in manifest["episodes"]["test"]]
    assert contract_digests(assignment, test_ids) == {
        k: lock[k] for k in ("prompts_sha256", "schemas_sha256")
    }, "dialect prompts or grammars changed"


def verify_expert_rows(manifest, assignment, pool, published, limit=None):
    """``published`` is the JSONL bytes of the expert rows for ``pool``."""
    rows, _ = expert_rows(manifest, assignment, pool, limit)
    assert "".join(dumps(r) + "\n" for r in rows).encode() == published, pool
    return len(rows)


def learner_prefix(row):
    """The learner's actions before this state, in canonical form, from the stored conversation."""
    spec_id = row["spec_id"]
    dialect = dialect_named(row["dialect"])
    translator = Translator(dialect, seed=spec_id)
    start = len(initial_messages(dialect, "x"))
    written = [json.loads(m["content"]) for m in row["messages"][start:] if m["role"] == "assistant"]
    return translator, [translator.to_canonical(a) for a in written]


def verify_dagger_rows(manifest, rows, every=1):
    specs = {s["id"]: s for pool in manifest["episodes"].values() for s in pool}
    checked = 0
    for index, row in enumerate(rows):
        if index % every:
            continue
        translator, prefix = learner_prefix(row)
        label, verified, _ = label_state(specs[row["spec_id"]], prefix)
        assert verified and translator.from_canonical(label) == row["target"], (
            row["spec_id"],
            row["step"],
        )
        checked += 1
    return checked


def verify_reports(reports, read_trace, manifest, assignment, lock, replay_every=1):
    """``reports`` are evaluation reports; ``read_trace(report, row)`` returns a trace's bytes."""
    specs = {s["id"]: s for pool in manifest["episodes"].values() for s in pool}
    replayed = 0
    for report in reports:
        arm = report["arm"]
        key = arm["name"] if arm.get("seed") is None else f"{arm['name']}-{arm['seed']}"
        assert report["status"] == "completed" and report["created_at"] > lock["locked_at"], key
        for field in ("manifest_sha256", "assignment_sha256", "source_sha256"):
            assert report[field] == lock[field], (key, field)
        if key in lock["adapters"]:
            assert report["adapter_sha256"] == lock["adapters"][key]["sha256"], key
        for index, row in enumerate(report["rows"]):
            raw = read_trace(report, row)
            assert sha(raw) == row["trace_sha256"], row["spec_id"]
            dialect = dialect_named(assignment["episodes"][row["spec_id"]])
            assert {k: row[k] for k in dialect_columns(dialect)} == dialect_columns(dialect)
            if index % replay_every:
                continue
            trace = json.loads(raw)
            written = [d["written"] for d in trace["decisions"] if "action" in d]
            again = run_dialect_episode(
                specs[row["spec_id"]], dialect, forced=written, max_tools=len(written)
            )
            for part in ("observations", "verdict", "diagnostics"):
                assert again[part] == trace[part], (key, row["spec_id"], part)
            replayed += 1
        assert summarize(report["rows"]) == report["summary"], key
    return replayed
