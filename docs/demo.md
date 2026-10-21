# A four-minute demo

## Prepare

Start `resolvelab serve` and open `http://127.0.0.1:8765`. For live inference, start
Ollama and install `qwen3:4b`. Keep the release evaluation report open in another
tab; inference speed depends on the local GPU.

## 1. Show the problem (40 seconds)

Select **Committed, then disconnected** (scenario `lost_response`) and **Legacy retry**.
Run the recovery. Open the first `sync_records` event: the response reports a
connection failure even though data was written. Show how repeating append can
create duplicates and how the independent verdict rejects a success claim.

Suggested narration:

> A plausible final answer is insufficient for a support agent that changes data.
> Here the first write committed, but its acknowledgement was lost. My evaluation
> checks the resulting database, so a retry that creates duplicates fails.

## 2. Show the real local agent (90 seconds)

Switch to **Local LLM · Ollama**. Run the same scenario. Expand model decisions
and tool results. Explain that the runtime validates the model's arguments; it
does not replace its decisions with a rule policy. The outcome appears only
after the episode ends.

If a model fails, show its trace and the rejected outcome honestly. The reference
policy is available for a fast deterministic demonstration and is labeled scripted.

## 3. Show the permission boundary (35 seconds)

Select the read-only scenario. Use the reference policy for an immediate run,
or the local model if time permits. Show the escalation ticket and unchanged
destination. Explain why correct escalation counts as passing the assigned task
but is not counted as a resolved sync.

## 4. Show evaluation and engineering evidence (55 seconds)

Open **Post-training**. Show the base/SFT denominator, false claims, resolved tasks,
escalations and per-template outcomes. Explain that the checkpoint was selected on
development loss before test inference. Download the evidence; point to the raw
trajectories and `python scripts/verify_experiment.py`, which re-executes their tools.
Show the tests covering concurrent retries, transaction rollback, action-loss
equivalence, split leakage and provider failures.

Close with what you would improve:

> The first post-training experiment tests held-out combinations of known faults.
> The next step is a new service adapter and a new holdout, plus repeated training
> seeds. Those would test whether the result survives beyond this small environment.

## Interview questions to prepare

1. Why do idempotency and upsert solve different problems?
2. How can a failed HTTP response still correspond to a successful write?
3. What does the independent checker know that the model does not?
4. Why are the runbook reference and naive retry unsuitable claims of model improvement?
5. What happens if the process crashes between a commit and a conversation checkpoint?
6. Why is a new data seed weaker than a new held-out task family?
7. Which guarantees change when the SQLite service becomes an external API?
8. Why supervise only action tokens, and how was the loss implementation verified?
9. Why can lower development loss coexist with failures during model rollouts?
10. Why does the bootstrap resample templates rather than individual record seeds?
