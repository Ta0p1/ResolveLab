"""Scripted oracle for fixture validation / imitation data, never a learned baseline."""

import re

from .schema import action


def reference_next(task, observations):
    reference, priority, status = re.search(
        r"external_ref (\S+), set priority to (\w+) and status to (\w+)\.", task
    ).groups()
    if observations:
        last = observations[-1]
        result = last["result"]
        if last["name"] == "escalate":
            return action("finish", outcome="escalated")
        if result.get("status") == 403:
            return action(
                "escalate", reason="Write permission was revoked; operator access is required."
            )
        if result.get("status") == 429:
            return action("wait", seconds=int(result["retry_after"]))
    target = None
    cursor = ""
    for obs in observations:
        if obs["name"] == "list_tickets" and obs["result"].get("status") == 200:
            body = obs["result"]["body"]
            cursor = body["next_cursor"]
            for ticket in body["tickets"]:
                if ticket["external_ref"] == reference:
                    target = ticket["id"]
    if target is None:
        return action("list_tickets", cursor=cursor)
    if not observations or observations[-1]["name"] != "get_ticket":
        return action("get_ticket", ticket_id=target)
    result = observations[-1]["result"]
    if all(result["body"][k] == v for k, v in {"priority": priority, "status": status}.items()):
        return action("finish", outcome="resolved")
    attempt = sum(o["name"] == "patch_ticket" for o in observations)
    return action(
        "patch_ticket",
        ticket_id=target,
        etag=result["etag"],
        priority=priority,
        status=status,
        idempotency_key=f"update-{attempt}",
    )
