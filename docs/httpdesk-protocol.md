# CaseDesk experiment protocol — registered before model runs

The second service is a synthetic ticket system behind a real loopback HTTP server.
It is not an integration with a commercial SaaS account. The agent searches paginated
tickets by exact reference, changes requested priority/status using an ETag, preserves
unrelated records, and verifies with a fresh GET. HTTP faults include 412 conflicts,
429 backoff, a 502 after a committed PATCH, and permission revocation after a readable
ticket advertised write access. Concurrent completion and already-correct tasks test
whether the agent can avoid unnecessary writes. Ticket text is untrusted.

## Registration

`benchmarks/httpdesk-v1.json` is frozen before any CaseDesk model inference or training.
All splits use new task records, references and seeds, disjoint from composition-v1.
Train contains single mechanisms; development and test contain disjoint compositions.
The test has 10 templates × 3 seeds = 30 episodes. Templates, not record variants,
are the bootstrap unit. This measures composition generalization inside one synthetic
API contract, not unseen APIs or production performance. The test is public after release.

The manifest may be used to validate the environment with the scripted oracle. The
oracle may see only the same task and tool observations as a model. Its result is an
environment check, never a model baseline. Test episodes never become SFT data.

## Comparators and selection

- Qwen3-0.6B with JSON Schema constrained decoding and one verified training example.
- Qwen3-1.7B with the identical one-shot prompt, schema and action/context budgets.
- Qwen3-0.6B with action-only LoRA and the identical constrained decoder.
- Three registered training seeds: 3407, 42, 2026. Each checkpoint selected by minimum
  development action-token loss; no test-based checkpoint or seed selection.

Exact model revisions and training defaults are in `httpdesk-sft-v1.json`. Greedy
non-thinking generation; 192 output tokens, 8192 context tokens, 24 tool actions.
No model-output repair, retry, state-dependent grammar, forced tool choice or scripted
recovery in model arms. The schema includes every tool at every step and only public
types/enums. IDs, cursors, ETags and keys are unconstrained strings: selecting valid
values and the next action is the model's responsibility. Development smoke runs may
fix implementation defects and improve the shared prompt before the final source and
prompt hash are locked. All model arms are evaluated on test only after that lock.
Any test-discovered changes require a separately named exploratory report, not an
overwrite of the registered comparison.

## Outcomes

Primary: independently verified terminal outcome (correct state + fresh verification,
or justified escalation following an actual 403). Wrong-record writes, changed
protected fields, redundant committed writes, and unsupported success claims fail.
Report JSON parse validity and typed-call validity separately from semantic success;
include context exhaustion, protocol failures and budget exhaustion in denominators.
Also report HTTP errors handled, tool calls, generated tokens, measured latency,
unsafe mutations and false success claims. Equal tool/token limits do not imply
equal latency or compute across model sizes. Paired comparisons include regressions
and template-cluster bootstrap intervals; three training seeds do not establish
generalization to other model families.

Raw actions, HTTP requests/responses, independent final snapshots and hashes are
retained. GPU-free replay re-executes the recorded actions against the HTTP service
and compares observations and verdicts. Freeze source, schema, prompt, manifest,
configuration, training data and adapter hashes before test evaluation.

## Development-only amendment (before test access)

Initial zero-shot development runs had valid tool calls but hallucinated IDs (0.6B)
and repeated pagination (1.7B). To strengthen both baselines, the final shared prompt
includes one complete, verified `train_plain / 4101` conversation. The same example
is supplied to every base and SFT arm. It is packaged as `httpdesk/demo.json`, rebuilt
by `scripts/build_http_demo.py`, and covered by source/prompt hashes. It contains no
fault recovery examples and no development/test records. Initial development runs
are exploratory, not part of the final paired test. This amendment changes the
registered zero-shot comparison to a stronger one-shot comparison before test runs.

The final decoder uses a fixed JSON field order (`name` before `arguments`, then
the public parameter declaration order). This reduces branch ambiguity in the
grammar and is identical for all arms. Demonstrations and training targets use
that same serialization. Field order does not restrict which tool or argument
value the model can choose. Development-only variants remain archived.
