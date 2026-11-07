"""Durable CaseDesk: the same HTTP contract and graders on persisted state, with process faults.

The v0.3 service keeps records and idempotency receipts in process memory, so a restart loses
them. Here the frozen handlers run in uvicorn worker processes over a shared SQLite store (WAL,
one write transaction per request). Crash points kill a worker before or after a commit, the
supervisor restarts it on the same store, two workers can receive the same PATCH at once, and
a grader extension checks exactly-once across restarts on top of grader v2.

Nothing under ``httpdesk/``, ``casedesk/`` or ``dialects/`` changes; this package imports them.
See ``docs/durable-recovery.md``.
"""

from .episodes import EXPERIMENT

__all__ = ["EXPERIMENT"]
