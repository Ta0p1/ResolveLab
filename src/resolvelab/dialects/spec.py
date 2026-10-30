"""API dialects: the CaseDesk contract re-skinned, with the same faults and grader underneath.

A dialect renames the six tools and their arguments, the response fields and the value
vocabularies (priorities, statuses, outcomes), and changes four structural conventions:

- the concurrency token: a quoted ETag ``"v5"`` (the study's), an integer revision ``5``, a
  weak ETag ``W/"5"`` or a version tag ``rev-5``;
- pagination: ``page-N`` cursors (the study's), opaque per-episode tokens, integer offsets or
  page numbers;
- status codes for conflict, rate limit, lost acknowledgement, denial and key reuse;
- the unit of waiting and of the rate-limit hint: seconds or milliseconds.

``CANONICAL`` is the study's own contract; rendering it reproduces the v0.4 prompt and
observations byte for byte (tested). ``generate(seed, split)`` draws a dialect. The
``heldout`` split draws every identifier (tool, argument, field, value and error names) from
pools disjoint from ``train`` and from the canonical contract, so a held-out dialect is
lexically unseen; the structural conventions occur in both splits.
"""

import random
from dataclasses import dataclass

TOOLS = ["list_tickets", "get_ticket", "patch_ticket", "wait", "escalate", "finish"]
PRIORITIES = ["low", "normal", "high", "urgent"]
STATUSES = ["open", "pending", "resolved"]
OUTCOMES = ["resolved", "escalated"]
TOKEN_STYLES = ["etag", "revision", "weak_etag", "version_tag"]
CURSOR_STYLES = ["page", "opaque", "offset", "page_number"]


@dataclass(frozen=True)
class Dialect:
    name: str
    noun: str
    nouns: str
    tools: dict  # canonical tool -> dialect tool
    args: dict  # canonical argument -> dialect argument
    fields: dict  # canonical response field -> dialect field
    priorities: dict  # canonical value -> dialect value
    statuses: dict
    outcomes: dict
    token: str  # one of TOKEN_STYLES
    cursor: str  # one of CURSOR_STYLES
    codes: dict  # canonical HTTP status -> dialect status
    errors: dict  # canonical error string -> dialect error string
    unit: str  # "seconds" or "milliseconds"

    def __post_init__(self):
        """Reject a dialect in which two names the agent must tell apart coincide."""
        body = ["id", "external_ref", "priority", "status", "assignee", "note", "write_allowed"]
        top = ["retry_after"]
        (body if self.token in ("revision", "version_tag") else top).append("etag")
        groups = {
            "tools": list(self.tools.values()),
            "arguments": list(self.args.values()),
            "record fields": [self.fields[f] for f in body],
            "response keys": ["status", "body"] + [self.fields[f] for f in top],
            "priorities": list(self.priorities.values()),
            "statuses": list(self.statuses.values()),
            "outcomes": list(self.outcomes.values()),
            "errors": list(self.errors.values()),
            "codes": [self.codes[c] for c in (403, 409, 412, 429, 502)],
        }
        for group, names in groups.items():
            if len(set(names)) != len(names):
                raise ValueError(f"Dialect {self.name}: duplicate {group} {names}")

    def identifiers(self):
        """Every API identifier the agent reads or writes, excluding the shared envelope."""
        names = set(self.tools.values()) | set(self.args.values()) | set(self.fields.values())
        for mapping in (self.priorities, self.statuses, self.outcomes, self.errors):
            names |= set(mapping.values())
        return names - ENVELOPE

    def describe(self):
        return {
            "name": self.name,
            "tools": dict(self.tools),
            "token": self.token,
            "cursor": self.cursor,
            "unit": self.unit,
            "codes": {str(k): v for k, v in self.codes.items()},
        }


CANONICAL = Dialect(
    name="canonical",
    noun="ticket",
    nouns="tickets",
    tools={t: t for t in TOOLS},
    args={
        a: a
        for a in (
            "cursor",
            "ticket_id",
            "etag",
            "priority",
            "status",
            "idempotency_key",
            "seconds",
            "reason",
            "outcome",
        )
    },
    fields={
        f: f
        for f in (
            "tickets",
            "id",
            "external_ref",
            "next_cursor",
            "priority",
            "status",
            "assignee",
            "note",
            "write_allowed",
            "updated",
            "waited_seconds",
            "ticket",
            "finished",
            "error",
            "commit_state",
            "etag",
            "retry_after",
        )
    },
    priorities={v: v for v in PRIORITIES},
    statuses={v: v for v in STATUSES},
    outcomes={v: v for v in OUTCOMES},
    token="etag",
    cursor="page",
    codes={c: c for c in (200, 201, 400, 403, 404, 409, 412, 428, 429, 502, 0)},
    errors={
        e: e
        for e in (
            "invalid_cursor",
            "not_found",
            "etag_and_key_required",
            "idempotency_conflict",
            "rate_limited",
            "permission_revoked",
            "precondition_failed",
            "upstream_response_lost",
        )
    },
    unit="seconds",
)

# Word pools: (train, heldout). Held-out words never appear in any train pool.
NOUNS = (
    [("case", "cases"), ("request", "requests"), ("issue", "issues"), ("incident", "incidents")],
    [("order", "orders"), ("job", "jobs"), ("booking", "bookings")],
)
VERBS = {
    "list_tickets": (["list", "search", "browse"], ["scan", "query"]),
    "get_ticket": (["get", "read", "fetch"], ["load", "inspect"]),
    "patch_ticket": (["update", "patch", "edit"], ["modify", "amend"]),
}
SINGLE = {
    "wait": (["wait", "sleep", "backoff"], ["pause", "delay"]),
    "escalate": (["escalate", "handoff", "raise_to_human"], ["refer", "page_operator"]),
    "finish": (["finish", "complete", "submit_result"], ["conclude", "report_done"]),
}
ARGS = {
    "external_ref": (["external_ref", "reference", "customer_ref"], ["client_ref", "source_ref"]),
    "priority": (["priority", "severity", "urgency"], ["importance", "impact"]),
    "status": (["status", "state", "stage"], ["phase", "condition"]),
    "idempotency_key": (["idempotency_key", "operation_id", "dedupe_key"], ["op_id", "txn_key"]),
    "reason": (["reason", "note", "summary"], ["why", "details"]),
    "outcome": (["outcome", "result", "verdict"], ["conclusion", "end_state"]),
    "assignee": (["assignee", "owner", "team"], ["handler", "crew"]),
    "note": (["note", "notes", "description"], ["remarks", "memo"]),
    "write_allowed": (["write_allowed", "editable", "can_edit"], ["mutable", "writable"]),
    "next_cursor": (["next_cursor", "next_page", "next"], ["continuation", "more"]),
}
TOKEN_ARGS = {
    "etag": (["etag", "if_match"], ["entity_tag", "match_tag"]),
    "revision": (["revision", "version"], ["generation", "seq"]),
    "weak_etag": (["etag_value", "cache_tag"], ["validator", "weak_tag"]),
    "version_tag": (["version_tag", "rev"], ["rev_label", "build_tag"]),
}
CURSOR_ARGS = {
    "page": (["cursor", "page_cursor"], ["position", "marker"]),
    "opaque": (["page_token", "cursor"], ["continuation_token", "bookmark"]),
    "offset": (["offset", "start"], ["skip", "from_index"]),
    "page_number": (["page", "page_no"], ["page_index", "sheet"]),
}
WAIT_ARGS = {
    "seconds": (["seconds", "delay_seconds"], ["pause_s", "wait_s"]),
    "milliseconds": (["milliseconds", "delay_ms"], ["pause_ms", "wait_ms"]),
}
VALUES = {
    "priority": (
        [PRIORITIES, ["p4", "p3", "p2", "p1"], ["minor", "moderate", "major", "critical"]],
        [["trivial", "regular", "elevated", "severe"], ["sev4", "sev3", "sev2", "sev1"]],
    ),
    "status": (
        [STATUSES, ["new", "waiting", "closed"], ["todo", "blocked", "done"]],
        [["active", "on_hold", "completed"], ["queued", "paused", "settled"]],
    ),
    "outcome": (
        [OUTCOMES, ["fixed", "handed_off"], ["done", "referred"]],
        [["success", "human_review"], ["accomplished", "transferred"]],
    ),
}
ERRORS = {
    "precondition_failed": (["precondition_failed", "stale_revision"], ["version_mismatch", "outdated"]),
    "rate_limited": (["rate_limited", "too_many_requests"], ["busy", "throttled"]),
    "upstream_response_lost": (
        ["upstream_response_lost", "ack_lost"],
        ["gateway_timeout", "reply_lost"],
    ),
    "permission_revoked": (["permission_revoked", "read_only"], ["forbidden", "locked"]),
    "idempotency_conflict": (["idempotency_conflict", "key_reused"], ["duplicate_key", "op_reused"]),
    "invalid_cursor": (["invalid_cursor", "bad_cursor"], ["bad_position", "unknown_marker"]),
    "not_found": (["not_found", "no_such_record"], ["missing", "unknown_id"]),
    "etag_and_key_required": (
        ["etag_and_key_required", "token_and_key_required"],
        ["guard_missing", "headers_missing"],
    ),
}
# Response fields for the wait receipt and the rate-limit hint, by unit.
HINTS = {
    ("waited_seconds", "seconds"): (["waited_seconds"], ["elapsed_s"]),
    ("waited_seconds", "milliseconds"): (["waited_ms"], ["elapsed_ms"]),
    ("retry_after", "seconds"): (["retry_after"], ["retry_in_s"]),
    ("retry_after", "milliseconds"): (["retry_after_ms"], ["retry_in_ms"]),
}
# Envelope keys shared by every dialect: the HTTP status/body wrapper and the finish receipt.
ENVELOPE = {"status", "body", "error", "finished", "escalation", "applied"}
CODE_CHOICES = {412: [412, 409], 429: [429, 503], 502: [502, 504], 403: [403, 423]}


def generate(seed, split="train"):
    """Draw a dialect. ``split`` is "train" or "heldout" (lexically disjoint from train)."""
    side = {"train": 0, "heldout": 1}[split]
    rng = random.Random(f"{split}:{seed}")
    noun, nouns = rng.choice(NOUNS[side])
    tools = {}
    for canonical, pools in VERBS.items():
        verb = rng.choice(pools[side])
        tools[canonical] = f"{verb}_{nouns}" if canonical == "list_tickets" else f"{verb}_{noun}"
    for canonical, pools in SINGLE.items():
        tools[canonical] = rng.choice(pools[side])
    token, cursor = rng.choice(TOKEN_STYLES), rng.choice(CURSOR_STYLES)
    unit = rng.choice(["seconds", "milliseconds"])
    words = {k: rng.choice(pools[side]) for k, pools in ARGS.items()}
    args = {
        "cursor": rng.choice(CURSOR_ARGS[cursor][side]),
        "ticket_id": f"{noun}_id" if side == 0 else f"{noun}_key",
        "etag": rng.choice(TOKEN_ARGS[token][side]),
        "priority": words["priority"],
        "status": words["status"],
        "idempotency_key": words["idempotency_key"],
        "seconds": rng.choice(WAIT_ARGS[unit][side]),
        "reason": words["reason"],
        "outcome": words["outcome"],
    }
    fields = {
        "tickets": nouns,
        "id": args["ticket_id"],
        "external_ref": words["external_ref"],
        "next_cursor": words["next_cursor"],
        "priority": words["priority"],
        "status": words["status"],
        "assignee": words["assignee"],
        "note": words["note"],
        "write_allowed": words["write_allowed"],
        "updated": f"updated_{noun}",
        "waited_seconds": HINTS["waited_seconds", unit][side][0],
        "ticket": "escalation",
        "finished": "finished",
        "error": "error",
        "commit_state": "applied",
        "etag": args["etag"],
        "retry_after": HINTS["retry_after", unit][side][0],
    }
    values = {key: rng.choice(pools[side]) for key, pools in VALUES.items()}
    codes = {c: c for c in CANONICAL.codes}
    for canonical, choices in CODE_CHOICES.items():
        codes[canonical] = rng.choice(choices)
    # Key reuse must stay distinguishable from a stale-token conflict.
    codes[409] = 422 if codes[412] == 409 else 409
    errors = {canonical: rng.choice(pools[side]) for canonical, pools in ERRORS.items()}
    return Dialect(
        name=f"{split}-{seed}",
        noun=noun,
        nouns=nouns,
        tools=tools,
        args=args,
        fields=fields,
        priorities=dict(zip(PRIORITIES, values["priority"])),
        statuses=dict(zip(STATUSES, values["status"])),
        outcomes=dict(zip(OUTCOMES, values["outcome"])),
        token=token,
        cursor=cursor,
        codes=codes,
        errors=errors,
        unit=unit,
    )
