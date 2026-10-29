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

## 4. Show the controlled study and its evidence (60 seconds)

In a terminal in the repository, run `python examples/casedesk_quickstart.py` (about two
seconds). The scripted teacher solves a registered test episode while the service injects a
429 and a 412. Then two recorded model runs on the same episode are replayed over real HTTP:
the behaviour-cloned adapter writes the ETag as `"\"v3\","`, receives 412 and loops until its
budget runs out; the DAgger adapter writes `"\"v3\""` and passes. Both are real model
decisions, not scripted traces.

Open [`artifacts/v0.4/RESULTS.md`](../artifacts/v0.4/RESULTS.md) and show the size-matched
comparison: 98.3% vs 90.8% over 120 independent episodes and three seeds, +7.5 pp with a
95% interval of [1.9, 13.3], and `bc-volume − bc` = 0.0. Explain that the study, its arms and
its decision rule were committed before any model run, that test inputs and adapters were
hash-locked before testing, and that `python scripts/verify_casedesk_v2.py` re-derives every
DAgger label and replays all 1,920 test episodes without a GPU.

Suggested narration:

> More expert data did nothing; labels at the states the model itself reaches fixed the
> failure. The gap is one compounding error expert demonstrations never contain: a
> mis-copied ETag that triggers a self-inflicted 412 loop.

If asked about the workbench's **HTTP study** page: it shows the earlier v0.3 study, which
the project later took apart. Its 30 test episodes were three records, and a counterfactual
that moves only the target showed the v0.3 adapters copying the demonstration's layout
(54/54 later-page targets with the published demo, 0/54 with the demo's target moved to page
one). See [the self-review](v0.3-review.md).

Close with what you would improve:

> This shows why learner-state labels help on one synthetic contract with a 0.6B model, not
> that they help everywhere. Next I would test transfer to a second, differently shaped API
> contract, compare against frontier models and an RL baseline that uses the audited grader
> as its reward, and make recovery durable across process restarts. Real SaaS integration
> remains separate engineering work.
