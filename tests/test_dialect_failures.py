"""The exploratory failure taxonomy of the dialect study, on hand-written rows and traces."""

import importlib.util
from pathlib import Path

import pytest

from resolvelab.casedesk.manifest import load_manifest
from resolvelab.casedesk.world import WorldState

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "summarize_dialect_failures", ROOT / "scripts/summarize_dialect_failures.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture(scope="module")
def episode():
    return load_manifest(ROOT / "benchmarks/casedesk-v2.json")["episodes"]["test"][0]


def row(error=None, category="unfinished", unsafe=0, dialect="canonical"):
    return {
        "dialect": dialect,
        "error": error,
        "failure_category": category,
        "unsafe_mutations": unsafe,
    }


def trace(episode, raw="", etags=(), commits=()):
    return {
        "spec": episode,
        "decisions": [{"error": "invalid", "usage": {"raw_output": raw}}] if raw else [],
        "observations": [
            {"name": "patch_ticket", "arguments": {"etag": etag}, "result": {"status": 412}}
            for etag in etags
        ],
        "commits": list(commits),
    }


@pytest.mark.parametrize(
    "token, bad",
    [('"v5"', False), ('"v12"', False), ('"v5",', True), ('"v5",v6"', True), ("5", True), (5, True)],
)
def test_malformed_recognises_the_canonical_token(token, bad):
    assert module.malformed(token) is bad


def test_invalid_output_counts_as_token_copying_only_inside_the_token_argument(episode):
    copying = trace(episode, raw='{"name": "patch_ticket", "arguments": {"etag": "\\"v4\\",v8')
    other = trace(episode, raw='{"name": "get_ticket", "arguments": {"ticket_id": "T-1')
    assert module.cause(row("json_error"), copying) == "token runs to output cap"
    assert module.cause(row("json_error"), other) == "other invalid output"
    assert module.cause(row("schema_error"), copying) == "other invalid output"


def test_budget_loops_separate_token_errors_from_repeated_writes(episode):
    target = WorldState(episode).target
    commit = {"id": target}
    assert module.cause(row("tool_budget"), trace(episode, etags=['"v4"x'])) == "malformed-token loop"
    assert (
        module.cause(row("tool_budget"), trace(episode, etags=['"v4"'], commits=[commit]))
        == "repeated-write loop"
    )
    assert module.cause(row("tool_budget"), trace(episode)) == "other budget loop"


def test_unsafe_writes_separate_the_wrong_record_from_wrong_values(episode):
    target = WorldState(episode).target
    unsafe = row(category="unsafe_mutation", unsafe=1)
    assert module.cause(unsafe, trace(episode, commits=[{"id": target}])) == "wrong-value write"
    assert module.cause(unsafe, trace(episode, commits=[{"id": "other"}])) == "wrong-record write"


def test_false_success_separates_no_write_from_a_refused_write(episode):
    claim = row(category="false_success")
    assert module.cause(claim, trace(episode)) == "claims success, no write attempted"
    assert module.cause(claim, trace(episode, etags=['"v4"'])) == "claims success after a refused write"


@pytest.mark.parametrize("category", ["spurious_escalation", "unjustified_escalation"])
def test_escalations_share_a_cause(episode, category):
    assert module.cause(row(category=category), trace(episode)) == "escalation error"


def test_every_other_failure_is_other(episode):
    assert module.cause(row(category="redundant_write"), trace(episode)) == "other"
