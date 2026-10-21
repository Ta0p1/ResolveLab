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

There are three distinct test record/task seeds, each reused under ten fault
compositions. Thus 30 episodes are not 30 independent customer requests. Training,
development and test reference identifiers are disjoint (6 / 2 / 3 respectively).

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

## Reproduction

### Supplementary larger control, registered before test inference

Add the locally installed `qwen3:4b` Q4_K_M model through Ollama JSON Schema output
as a separately labeled control. `httpdesk-ollama-control.json` pins its digest and
192-token / 8192-context / 24-action budgets. It receives the same base instructions,
training example and static schema. It has no parser repair, inference retry or
scripted fallback. Temperature 0, thinking disabled. Two CPU-only development probes
compared the original prompt (1/2 passed) with a task-continuity reminder (0/2).
The original prompt was selected before test access; both probes are archived.
The reminder configuration is empty in the locked test run.

This is **not** a matched training comparison: model size, quantization,
backend, chat template details and grammar implementation differ. The primary causal
adapter comparison remains HF 0.6B versus HF 0.6B + LoRA. Keep this control's
30 episodes separate from the primary 150. The test lock additionally hashes
its script and configuration. Token counts and model-load duration are retained.

Ollama implements schema enforcement through its `format` field; see its
[official structured-output documentation](https://docs.ollama.com/capabilities/structured-outputs).
The protocol uses [LM Format Enforcer](https://github.com/noamgat/lm-format-enforcer)
for the matched Transformers arms.

```bash
# Ollama running locally with the pinned qwen3:4b digest; Transformers is used only
# for tokenizer-based context guarding in this control, not for loading 4B weights.
python -m pip install transformers==4.57.6 jinja2==3.1.6
python scripts/http_ollama_control.py --split test --output .local/http-ollama-4b-test.json
```

### Primary study

Use the repository checkout and a CUDA GPU. The measured environment is Python
3.12, PyTorch 2.7.1+cu126 and the pinned optional packages. Install CUDA PyTorch
for your platform, then:

```bash
python -m pip install -e ".[dev]" -r requirements-training.txt
python scripts/http_experiment.py collect --output .local/http-data-ordered
python scripts/train_http_seeds.py
```

Collection executes 48 training and 8 development episodes over real HTTP. It
rejects any teacher trajectory that fails the independent grader. The teacher is
a hand-written runbook, not a larger language model. Training supervises only the
next action tokens, not observations or the fixed in-context demonstration.

`train_http_seeds.py` runs each registered seed in a separate process, then evaluates
its development-loss-selected checkpoint on development tasks. Reproduction
directories must be new; existing runs are never overwritten. The minimum-loss
checkpoint can differ slightly across GPU/library environments; record that change.

For the registered test, use the selected checkpoint from each `training.json`:

```bash
python scripts/http_experiment.py eval --split test --output .local/http-base-test.json
python scripts/http_experiment.py eval --split test --larger --output .local/http-large-test.json
# Example syntax; replace epoch-N with that seed's selected checkpoint:
python scripts/http_experiment.py eval --split test --seed 3407 --adapter .local/http-sft-3407/epoch-N --output .local/http-sft-3407-test.json
python scripts/http_experiment.py compare --base-report .local/http-base-test.json --sft-report .local/http-sft-3407-test.json --output .local/comparison-3407.json
```

Repeat the SFT evaluation for seeds 42 and 2026. Do not pick checkpoints using these
test scores. The original training/test locks remain historical evidence; create a
new experiment name/holdout for further tuning rather than overwriting them.

To audit the published results without a GPU or model downloads:

```bash
python scripts/verify_http_study.py
```

To inspect the API separately:

```bash
python scripts/serve_casedesk.py --seed 4101 --faults conflict lost_ack --port 8770
curl http://127.0.0.1:8770/tickets
```

The printed task identifies the target reference and requested values. The local
backend is unauthenticated and binds only to loopback. Its state is process-local;
neither remote crash recovery nor durable idempotency across restarts is claimed.
