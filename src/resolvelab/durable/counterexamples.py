"""Plausible wrong recoveries after a crash, kept so tests and the example can show them failing.

Each is the CaseDesk v2 teacher with one recovery step replaced. A request that got no
response is ``{"status": 0, "commit_state": "unknown"}``: the write may or may not have
committed, and the only way to know is to read the ticket again.
"""

from ..casedesk.teacher import teacher_next
from ..httpdesk.schema import action


def unanswered_patch(obs):
    return obs["name"] == "patch_ticket" and obs["result"].get("status") == 0


def claim_after_crash(task, observations):
    """Treats a write that got no response as done and claims success without reading again."""
    if observations and unanswered_patch(observations[-1]):
        return action("finish", outcome="resolved")
    return teacher_next(task, observations)


def new_key_retry(task, observations):
    """Re-reads for a fresh ETag, then writes again under a new key without checking the values."""
    if len(observations) >= 2:
        failed, read = observations[-2], observations[-1]
        if (
            unanswered_patch(failed)
            and read["name"] == "get_ticket"
            and read["result"].get("status") == 200
        ):
            args = failed["arguments"]
            return action(
                "patch_ticket",
                ticket_id=args["ticket_id"],
                etag=read["result"]["etag"],
                priority=args["priority"],
                status=args["status"],
                idempotency_key=args["idempotency_key"] + "-retry",
            )
    return teacher_next(task, observations)


def stale_etag_retry(task, observations):
    """Retries the same write at once under a new key. Not wrong here: If-Match turns it into a 412."""
    if observations and unanswered_patch(observations[-1]):
        args = observations[-1]["arguments"]
        return action("patch_ticket", **{**args, "idempotency_key": args["idempotency_key"] + "-retry"})
    return teacher_next(task, observations)


COUNTEREXAMPLES = {"claim_after_crash": claim_after_crash, "new_key_retry": new_key_retry}
