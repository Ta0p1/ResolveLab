# Defending the experiment in an interview

Use the [actual result table](../artifacts/v0.3/RESULTS.md) for numbers. Keep the
scope attached to every claim: a public synthetic composition holdout, not real
customer incidents or a general agent leaderboard.

## “Did you just teach the model to output JSON?”

That was a confound in v0.2, and its report says so. In v0.3 both untrained baselines
and all three LoRA policies use the same constrained decoder and tool schema.
The report measures call validity separately from task success. When a valid call
targets a similar-looking but wrong ticket, uses a stale ETag or announces success
without reading the final state, it remains a failure. Show one actual failed
baseline trace next to the matching adapted-model trace, not just aggregate scores.

The grammar fixes serialization order and types, not the next tool choice. Every
tool is available on every turn; IDs and ETags are not injected into grammar enums.
The same verified one-shot training example is present in all prompts.

Controlling format does not isolate abstract reasoning. End-to-end success also
requires exact reference matching, copying IDs and following the supplied runbook.
A baseline that fails before reaching an HTTP fault provides no direct comparison
of that fault's recovery skill. Inspect which errors each policy actually encountered;
describe the gain as improved execution of this contract, not general reasoning.

## “How independent is the evaluation?”

The model only sees the task and HTTP observations. The grader reads backend state,
the commit audit and read versions. It checks all records and protected fields,
not a natural-language success answer or an LLM judge. It also rejects a redundant
write on an already-correct ticket. A permitted concurrent operator update is
modeled separately from agent writes. The grader and scripted teacher are separate
implementations, with negative tests for false claims and wrong-record mutations.

A concrete example is the 1.7B baseline's
[`test_concurrent_injection / 6302`](../artifacts/v0.3/large-test/test_concurrent_injection-6302.json):
the concurrent operator completed the target, then the model wrote a different,
already-correct ticket and claimed success. Final payload equality was true, but
the commit audit recorded an unsafe and redundant write, and fresh target
verification was missing. Final-state equality alone would have missed this.
The matching [LoRA 3407 trace](../artifacts/v0.3/sft-3407-test/test_concurrent_injection-6302.json)
shows the independently verified alternative. The full reports retain every case.

GPU-free replay checks the published actions against a fresh HTTP server. This
audits tool/environment outcomes, not the model's probabilities or deterministic
re-generation of the same tokens on arbitrary hardware.

## “Could the train and test sets leak?”

The holdout manifest was committed before model runs (`7e5ffb4`). Templates and
record seeds are disjoint across train/development/test. The training loader rejects
test membership. Data, source, schema, prompt and weight hashes are recorded. Each
seed's checkpoint is selected by development loss, then locked before test inference.
All three seeds are reported. There is no test-based selection of the best seed.

The single in-context example is deliberately from training. Fault primitives and
the API contract are shared across splits; the experiment tests new compositions,
not unseen mechanisms or tools.

The v0.3 intervals resampled templates, and that was the wrong unit: all ten templates
reuse the same three records, and for the trained models the record alone decides the
outcome, which is why the interval collapsed to `[66.7, 66.7]`. v0.4 gives every episode
its own record and resamples training seeds and records separately; see the
[review](v0.3-review.md) and the [v2 protocol](casedesk-v2-protocol.md).

## “What did you find wrong with your own result?”

This is the strongest story in the project; tell it with the traces open.

1. Per-record outcomes showed the 30-episode test was three lookup problems: LoRA seeds
   3407/2026 pass every episode of two records and none of the third.
2. The matched 0.6B base never read the target ticket in any episode, so "0% → 77.8%"
   is a workflow/lookup gain; it says nothing about recovery against that base.
3. The failing record was the only one with its target in slot 0, the demo's target is
   in slot 3, and training never used slot 0. A counterfactual kept every record fixed
   and moved only the target (and, separately, the demo's target): all three adapters
   solve 54/54 later-page targets with the published demo and 0/54 when the demo's
   target is on page one. The adapters learned the demonstration's layout, not
   reference matching.
4. Two latent grader holes (resolving after a needless escalation; escalating before
   any denial) were fixed in grader v2; re-grading all 180 published traces changed no
   verdict, which is itself worth saying.
5. The scripted teacher mislabels learner states (21/91 perturbed states), so it could not
   be used for recovery data until it was rewritten and every label replay-verified.

What changed as a result: independent records with position as a declared factor,
an off-policy-safe teacher, and a DAgger study with a size-matched behaviour-cloning
control, registered with decision rules before any v2 model run.

## “Why DAgger, and not RL?”

Behaviour cloning trains only on states the expert visits. Once the learner makes one
mistake it is in a state with no correct example, so errors compound over the horizon
(quadratically in the worst case for BC, linearly for DAgger under its no-regret
assumptions; Ross & Bagnell 2010,
Ross, Gordon & Bagnell 2011). The re-listing loop in `sft-3407-test/test_conflict_lost-6303`
is exactly that. DAgger needs an expert that can be queried at any state; this project has
one (after making it off-policy safe), so it is cheaper and lower-variance than RL. RL is
the tool when no such expert exists. Its reward here is the grader, and the grader had two
holes until v2. A reward-hacking policy would have found them.

The control matters more than the algorithm: `bc-volume` adds the same number of extra
expert rows from the same training episodes as `dagger` adds learner-state rows, so a
difference is attributable to the state distribution, not to more data.

What happened ([results](../artifacts/v0.4/RESULTS.md)): 98.3% vs 90.8% on the locked test,
+7.5 pp with a seed × record interval of [1.9, 13.3]; `bc-volume − bc` was 0.0. Be ready to
show the mechanism from traces: behaviour cloning occasionally mis-copies an ETag, gets 412,
re-reads and repeats the same mis-copy until the budget runs out (or extends the string to
the output cap). 26 of 33 `bc-volume` failures are that loop; `dagger` has none, because the
learner produced those states in training rollouts and the teacher labelled the way out.
Expect the follow-up "isn't that a narrow fix?" — yes: it shows why learner-state labels help
here, on one contract; it is not evidence that DAgger helps everywhere. Also say that rows,
not tokens, were matched (DAgger rows carry 1–9% more target tokens per epoch).

## “What does the HTTP boundary actually add?”

The adapter sends real httpx requests over a bound TCP socket to a separate FastAPI
application. It handles status codes, If-Match, Idempotency-Key and Retry-After.
Tests include concurrent same-key requests and a 502 after a committed write.
The model must choose when to reread, back off, retry or escalate; the adapter
performs no hidden recovery. A separate CLI can run the backend in its own process.

The backend is synthetic and process-local. Its lock makes a write and receipt
atomic during that process lifetime; it does not provide durable remote exactly-once
execution. Production deployment would need persistent receipts, authentication,
tenant boundaries, job leases and explicit restart semantics.

## “Why LoRA and supervised actions instead of RL?”

The immediate bottleneck is following a verifiable recovery contract with a small
model. Verified expert trajectories provide a simple, auditable baseline. Loss is
applied only to next-action tokens; observations and demonstration tokens condition
the model without receiving direct loss. A numerical test compares the optimized
loss and gradients with ordinary masked causal-LM training.

Low token loss is not the task metric. An agent can enter states absent from expert
trajectories, and one incorrect action changes later observations. Rollout outcomes
and failure audits are therefore essential. v0.4 tests learner-state (DAgger) data
directly; RL should follow a reward audit, not precede it.

## “How much did the coding assistant do?”

Describe the collaboration accurately. This project was developed with substantial
AI assistance, including implementation, tests and experiment orchestration. Be ready
to explain the contracts, reproduce a run, diagnose an unseen failure and make a
change yourself. Repository stars and assisted code volume are not evidence that
you understand the system; a precise explanation and a live debugging session are.
