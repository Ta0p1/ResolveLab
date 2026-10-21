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
not unseen mechanisms or tools. Record variants share templates, so paired intervals
resample templates rather than pretending all episodes are independent. Even that
interval is descriptive for this small benchmark, not a production reliability bound.
The task wording is fixed, with only three distinct test record seeds. Paraphrase,
cross-schema and cross-domain robustness need separate frozen evaluations.

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
and failure audits are therefore essential. Off-policy states and a larger-model
baseline are useful next experiments; RL should follow a reward audit, not precede it.

## “How much did the coding assistant do?”

Describe the collaboration accurately. This project was developed with substantial
AI assistance, including implementation, tests and experiment orchestration. Be ready
to explain the contracts, reproduce a run, diagnose an unseen failure and make a
change yourself. Repository stars and assisted code volume are not evidence that
you understand the system; a precise explanation and a live debugging session are.
