"""Off-policy-safe runbook: a pure function of the task text and tool observations.

The v0.3 teacher is only correct on its own state distribution. Queried at a state reached
by a learner it can patch the target with the ETag of a different ticket it just read, or
claim "escalated" after an escalation that no denial justified. DAgger labels learner states,
so this teacher re-derives everything from the observation history and returns ``None``
when no correct continuation exists (an unsafe write may have committed, or an escalation was
already filed without an observed denial). Labels are still verified by replay before use.
"""

from ..httpdesk.schema import action
from .world import parse_task

COMMITTING = {200, 502, 0}


def locate(reference, observations):
    target, cursor = None, ""
    for obs in observations:
        result = obs["result"]
        if obs["name"] == "list_tickets" and result.get("status") == 200:
            cursor = result["body"]["next_cursor"]
            for row in result["body"]["tickets"]:
                if row["external_ref"] == reference:
                    target = row["id"]
    return target, cursor


def denial_observed(target, observations):
    for i, obs in enumerate(observations):
        result = obs["result"]
        if obs["arguments"].get("ticket_id") != target:
            continue
        if obs["name"] == "patch_ticket" and result.get("status") == 403:
            return i
        if obs["name"] == "get_ticket" and result.get("status") == 200:
            if result["body"].get("write_allowed") is False:
                return i
    return None


def pending_wait(observations):
    limited = [i for i, o in enumerate(observations) if o["result"].get("status") == 429]
    if not limited:
        return 0
    last = limited[-1]
    waited = sum(o["arguments"]["seconds"] for o in observations[last + 1 :] if o["name"] == "wait")
    return int(observations[last]["result"].get("retry_after", 1)) - waited


def teacher_next(task, observations):
    reference, priority, status = parse_task(task)
    desired = {"priority": priority, "status": status}
    target, cursor = locate(reference, observations)
    patches = [(i, o) for i, o in enumerate(observations) if o["name"] == "patch_ticket"]
    for _, obs in patches:
        args = obs["arguments"]
        if obs["result"].get("status") in COMMITTING and (
            args["ticket_id"] != target or any(args[k] != v for k, v in desired.items())
        ):
            return None
    escalations = [i for i, o in enumerate(observations) if o["name"] == "escalate"]
    denial = denial_observed(target, observations) if target else None
    if escalations:
        if denial is not None and denial < escalations[0]:
            return action("finish", outcome="escalated")
        return None
    wait = pending_wait(observations)
    if observations and observations[-1]["result"].get("status") == 429 and wait > 0:
        return action("wait", seconds=min(wait, 60))
    if denial is not None:
        return action("escalate", reason="Write permission was revoked; operator access is required.")
    if target is None:
        return action("list_tickets", cursor=cursor)
    last_patch = max((i for i, o in patches if o["arguments"]["ticket_id"] == target), default=-1)
    reads = [
        i
        for i, o in enumerate(observations)
        if o["name"] == "get_ticket"
        and o["arguments"]["ticket_id"] == target
        and o["result"].get("status") == 200
    ]
    if not reads or reads[-1] < last_patch:
        return action("get_ticket", ticket_id=target)
    read = observations[reads[-1]]["result"]
    if all(read["body"][k] == v for k, v in desired.items()):
        return action("finish", outcome="resolved")
    if wait > 0:
        return action("wait", seconds=min(wait, 60))
    used = {o["arguments"]["idempotency_key"] for _, o in patches}
    attempt = 0
    while f"update-{attempt}" in used:
        attempt += 1
    return action(
        "patch_ticket",
        ticket_id=target,
        etag=read["etag"],
        priority=priority,
        status=status,
        idempotency_key=f"update-{attempt}",
    )
