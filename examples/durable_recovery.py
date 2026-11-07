"""Durable recovery in one minute, no GPU: a worker dies after committing, and is restarted.

1. The scripted teacher on an episode whose worker process exits right after the write is
   durable and before it responds. The teacher reads the ticket again on the restarted
   process, sees its write, and stops.
2. Two plausible wrong recoveries on the same episode: writing again under a new key, and
   claiming success without reading after the restart. The durable grader rejects both.
3. The teacher once more, on an episode whose service restarts after the write, but with the
   v0.3-style process-local store: the acknowledged write is gone after the restart.
4. Two worker processes on one store receive the same PATCH at the same instant.

    python examples/durable_recovery.py
"""

from resolvelab.casedesk.world import WorldState
from resolvelab.durable.counterexamples import claim_after_crash, new_key_retry
from resolvelab.durable.episodes import episodes_by_id
from resolvelab.durable.race import race
from resolvelab.durable.runner import run_durable_episode

EPISODES = episodes_by_id()


def show(title, trace):
    print(f"  {title}")
    for obs in trace["observations"]:
        keys = ("cursor", "ticket_id", "idempotency_key")
        args = " ".join(f"{k}={obs['arguments'][k]}" for k in keys if k in obs["arguments"])
        status = obs["result"].get("status", "-")
        note = "  (no response)" if status == 0 else ""
        print(f"    {obs['name']:<13} {args[:60]:<62} -> {status}{note}")
    boots = ", ".join(f"{b['kind']}:{b['ended_by'] or '-'}" for b in trace["boots"])
    verdict = trace["verdict"]
    outcome = "PASS" if verdict["passed"] else f"FAIL ({verdict['failure_category']})"
    print(f"    processes: {boots}")
    print(
        f"    grader: {outcome}; commits={verdict['commits']}, "
        f"duplicate key commits={verdict['duplicate_key_commits']}, "
        f"lost acknowledged={verdict['lost_acknowledged_commits']}, restarts={verdict['restarts']}\n"
    )
    return verdict


def main():
    crash = EPISODES["durable-crash_after-00"]
    print(f"Episode {crash['id']}: faults {crash['faults']}\n  task: {WorldState(crash).task}\n")
    assert show("Scripted teacher:", run_durable_episode(crash))["passed"]
    wrong = show("New key after the crash:", run_durable_episode(crash, policy=new_key_retry))
    assert wrong["failure_category"] == "redundant_write"
    wrong = show(
        "Claim without a read after restart:", run_durable_episode(crash, policy=claim_after_crash)
    )
    assert wrong["failure_category"] == "unverified_after_restart"

    restart = EPISODES["durable-restart-00"]
    print(f"Episode {restart['id']}: faults {restart['faults']}")
    lost = show("Scripted teacher, process-local store:", run_durable_episode(restart, store="process"))
    assert lost["failure_category"] == "lost_acknowledged_commit"

    print("Two workers, one store, four identical PATCHes released together:")
    responses, snapshot = race("same_key")
    print(f"    responses {sorted(r['status'] for r in responses)}, commits {len(snapshot.commits)}")
    assert len(snapshot.commits) == 1
    print("\nMore: docs/durable-recovery.md, `resolvelab durable --help`")


if __name__ == "__main__":
    main()
