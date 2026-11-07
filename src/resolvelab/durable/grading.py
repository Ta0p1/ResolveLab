"""Durable grader: grader v2, then exactly-once across restarts.

Grader v2 runs unchanged on the recovered store (``store.Snapshot``). On top of it:

- **No duplicate commits.** An idempotency key commits at most once
  (``duplicate_key_commits``), and v2's ``redundant_commits`` (a write whose ticket already
  held the requested values) stays zero.
- **No lost acknowledged commits.** Every boot after the first records the version of each
  record it recovered. A commit is lost when a later boot recovered an older version of its
  ticket; it was acknowledged when a PATCH for its key was answered 200 and the response
  was delivered. The final recovery after the episode counts as a boot.
- **Fresh read after restart.** A resolved claim needs v2's fresh verifying read, served
  after the last restart of the episode (``epoch``).

``passed`` requires v2 to pass and all three. Failure categories add ``duplicate_commit``,
``lost_acknowledged_commit`` and ``unverified_after_restart`` to v2's.
"""

from collections import Counter

from ..casedesk.grading import diagnose, grade_v2


def duplicate_key_commits(commits):
    return sum(count - 1 for count in Counter(c["key"] for c in commits).values())


def acknowledged(snapshot):
    """Sequence numbers of commits whose PATCH was answered 200 and delivered."""
    seqs = set()
    for event in snapshot.http_events:
        if event["method"] != "PATCH" or event["status"] != 200 or not event["delivered"]:
            continue
        key = event["request"]["Idempotency-Key"]
        matching = [
            c["seq"] for c in snapshot.commits if c["key"] == key and c["seq"] <= event["commits_seen"]
        ]
        if matching:
            seqs.add(max(matching))
    return seqs


def lost_commits(snapshot):
    """Commits a later boot did not recover, each with whether the client had been told."""
    told = acknowledged(snapshot)
    lost = {}
    for boot in snapshot.boots:
        if boot["kind"] == "start":
            continue
        for commit in snapshot.commits:
            if commit["seq"] > boot["commits_seen"] or commit["seq"] in lost:
                continue
            if boot["recovered"][commit["id"]] < commit["after"]["version"]:
                lost[commit["seq"]] = {
                    "seq": commit["seq"],
                    "ticket_id": commit["id"],
                    "lost_at_boot": boot["boot"],
                    "acknowledged": commit["seq"] in told,
                }
    return sorted(lost.values(), key=lambda row: row["seq"])


def restarts(snapshot):
    return sum(boot["kind"] == "restart" for boot in snapshot.boots)


def fresh_after_restart(snapshot):
    ticket = snapshot.tickets[snapshot.target]
    epoch = restarts(snapshot)
    return any(
        r["id"] == snapshot.target
        and r["version"] == ticket["version"]
        and r["after_commits"] == len(snapshot.commits)
        and r["epoch"] == epoch
        for r in snapshot.reads
    )


def grade_durable(snapshot, claim):
    verdict = grade_v2(snapshot, claim)
    duplicates = duplicate_key_commits(snapshot.commits)
    lost = lost_commits(snapshot)
    lost_told = sum(row["acknowledged"] for row in lost)
    restarted = restarts(snapshot)
    fresh = fresh_after_restart(snapshot)
    exactly_once = not duplicates and not lost_told and not verdict["redundant_commits"]
    verified = claim != "resolved" or fresh
    passed = verdict["passed"] and exactly_once and verified
    if passed:
        category = None
    elif duplicates:
        category = "duplicate_commit"
    elif lost_told:
        category = "lost_acknowledged_commit"
    elif (
        claim == "resolved"
        and restarted
        and not fresh
        and verdict["exact_state"]
        and verdict["failure_category"] in (None, "false_success")
    ):
        category = "unverified_after_restart"
    else:
        category = verdict["failure_category"]
    return {
        **verdict,
        "grader": "casedesk_durable_v1",
        "passed": bool(passed),
        "failure_category": category,
        "false_success": claim == "resolved" and not passed,
        "v2_passed": verdict["passed"],
        "v2_failure_category": verdict["failure_category"],
        "exactly_once": bool(exactly_once),
        "duplicate_key_commits": duplicates,
        "lost_commits": len(lost),
        "lost_acknowledged_commits": lost_told,
        "restarts": restarted,
        "fresh_after_restart": fresh,
    }


def diagnose_durable(snapshot, observations, duplicates=()):
    """v2 diagnostics plus what the process faults did. Never part of the verdict."""
    return {
        **diagnose(snapshot, observations),
        "boots": [
            {k: boot[k] for k in ("boot", "worker", "kind", "exit_code", "ended_by")}
            for boot in snapshot.boots
        ],
        "process_faults_fired": sorted(r["name"] for r in snapshot.chaos if r["fired_boot"] is not None),
        "requests_without_response": sum(o["result"].get("status") == 0 for o in observations),
        "duplicate_deliveries": len(duplicates),
        "lost": lost_commits(snapshot),
    }
