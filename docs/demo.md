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

## 4. Show controlled evaluation and engineering evidence (55 seconds)

Open **HTTP study**. Show the call-validity and task-success columns separately.
All five arms use the same grammar and one-shot example. Select a baseline failure
and the same task under LoRA; expand HTTP requests and show whether the correct
ticket was written and verified. Do not substitute a scripted trace for a model run.
Explain development-loss checkpoint selection and the three reported seeds.
Download the evidence and point to `python scripts/verify_http_study.py`, which
replays all published test actions through actual HTTP sockets without a GPU.

Close with what you would improve:

> This comparison controls the output-format confound and repeats training, but it
> still tests known mechanisms within a synthetic API. Next I would add off-policy
> failure states and evaluate a stronger reasoning model on a newly frozen holdout.
> Durable remote recovery and real SaaS integration remain separate engineering work.

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

See [interview notes](interview-notes.md) for evidence-backed answers and limitations.
