# Evaluate your own model on CaseDesk

```bash
resolvelab casedesk episodes --pool dev                       # list registered episodes
resolvelab casedesk run --episode test-test_conflict_rate-07 --model ollama:qwen3:4b
resolvelab casedesk eval --pool dev --model ollama:qwen3:4b --output runs/qwen3-4b-dev.json
```

`run` prints one episode's tool calls and the grader's verdict. `eval` writes a resumable
report (`--resume` continues an interrupted run; the report refuses to mix models, manifests
or code versions) and one trace per episode next to it, in the same format as the published
v0.4 evidence. Pass, unsafe writes, false success, spurious escalations, tokens and latency
are summarised at the end.

## Models

| Spec | Backend | Output constraint | Install |
|---|---|---|---|
| `teacher` | scripted runbook (environment check, not a model) | n/a | base |
| `hf:Qwen/Qwen3-0.6B[@rev]` | local Transformers on a CUDA GPU | the study's JSON Schema, token-level (LM Format Enforcer) | `requirements-training.txt` |
| `ollama:<model>` | local [Ollama](https://ollama.com) native API | the study's JSON Schema as `format` | Ollama + `ollama pull <model>` |
| `openai:<model>` | any OpenAI-compatible server (vLLM, SGLang, OpenRouter, OpenAI) | portable JSON Schema via `response_format` | base |
| `anthropic:<model>` | Claude through the Anthropic SDK | portable JSON Schema via `output_config.format` | `pip install "resolvelab[anthropic]"` |

Options are `--option KEY=VALUE`, repeatable:

- `hf`: `adapter=<LoRA dir>`, `thinking=<tokens>` (Qwen3 thinking mode), `max_output`, `context`.
  The revision defaults to the one pinned in `benchmarks/casedesk-v2-study.json`.
- `ollama`: `base_url`, `num_ctx` (8192), `max_output` (192), `temperature` (0), `seed` (42),
  `think` (false), `keep_alive` (10m).
- `openai`: `base_url` (or `OPENAI_BASE_URL`), `api_key_env` (OPENAI_API_KEY), `max_output`,
  `temperature` (0, or `none`), `token_field` (`max_tokens` or `max_completion_tokens`),
  `strict` (true), `extra` (a JSON object merged into every request, e.g. vLLM's
  `{"chat_template_kwargs": {"enable_thinking": false}}`).
- `anthropic`: `effort` (high; `none` to omit), `max_tokens` (16000). Credentials resolve the
  SDK's way (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` or an `ant auth login` profile).

API keys are read from the environment and never written to reports.

Reports record no local paths either. A local `adapter=` directory, or an `hf:` model given as
a directory, is recorded relative to the checkout when it lies inside it, and otherwise by its
directory name, with the adapter's `adapter_sha256` beside it; a drive letter, home directory
or user name never reaches a report. Hub ids are recorded as given. Reports published before
this rule, such as the v0.4 and v0.5 evidence, stay as published.

## Running episodes concurrently

`eval --workers N` runs N episodes at once (default 1, one after another). Each episode has
its own world and its own HTTP server on a free port, so episodes share nothing but the model.
The report is the same: the same rows in manifest order, whatever order episodes finish in,
the same traces and the same identity check, and `--resume` continues an interrupted run with
any number of workers. With the scripted teacher on the dev pool, `--workers 8` writes the
rows and traces of `--workers 1` apart from timing (`tests/test_parallel_eval.py`).

| Provider | `--workers > 1` | Why |
|---|---|---|
| `teacher` | yes | scripted, no model |
| `hf:` | no, refused before the model loads | one GPU model in this process decodes one sequence at a time; serve it with vLLM and use `openai:` instead |
| `openai:` | yes | each running episode has its own client; the server batches the requests |
| `anthropic:` | yes | each running episode has its own provider instance, because the provider replays that episode's own earlier turns |
| `ollama:` | yes | Ollama decodes up to `OLLAMA_NUM_PARALLEL` requests at once and queues the rest |

Things to check before raising N:

- **Queued requests time out.** A request that waits in a server queue spends its `timeout`
  (300 s by default) waiting. For Ollama, set `OLLAMA_NUM_PARALLEL` to at least N on the
  server (each slot reserves its own `num_ctx` of memory). vLLM schedules up to its
  `--max-num-seqs` requests at once.
- **Rate limits end episodes.** `openai:` does not retry and `anthropic:` retries only as the
  SDK does (twice for 408/409/429/5xx). An episode whose request still fails ends with
  `error: inference_error` and counts as a failure, so keep N within the API's rate limit and
  check the rows' `error` field before quoting a score.
- **Batching is not bit-identical.** A server that batches requests need not decode exactly as
  it does one request at a time, so a model's outputs can differ slightly between worker
  counts, as they can between server versions.

A Qwen3 model on vLLM, with thinking off and 16 episodes at a time:

```bash
vllm serve Qwen/Qwen3-8B --served-model-name qwen3-8b --max-model-len 8192
resolvelab casedesk eval --pool dev --output runs/qwen3-8b-dev.json \
  --model openai:qwen3-8b --option base_url=http://127.0.0.1:8000/v1 \
  --option 'extra={"chat_template_kwargs":{"enable_thinking":false}}' --workers 16
```

The single quotes keep the shell from removing the JSON's double quotes. Name the served model
with `--served-model-name`: without it vLLM serves the model under its path, and that path is
the model name the report records.

`resolvelab durable run --model` runs one episode; the durable suite has no model command that
runs several, so it has no `--workers`.

## What is and is not comparable

Every provider sees the identical conversation: the study's system prompt, its one-shot
demonstration, the task, then each action and observation. No provider repairs, retries or
replaces a model's decision; text that is not a valid action ends the episode as a failure.

- **`hf:` arms reproduce the registered study's decoding exactly.** Results with the
  published adapters are directly comparable to `artifacts/v0.4/RESULTS.md`.
- **`ollama:` uses the same schema with a different decoder and quantised weights**, like the
  v0.3 supplementary control. Ollama truncates prompts beyond `num_ctx` silently, so a reply
  whose prompt filled the window is failed as `context_limit` rather than scored.
- **`openai:` and `anthropic:` need an object at the schema root**, so they get the portable
  schema: `name` is an enum of the six tools and `arguments` an `anyOf` of their argument
  schemas, without numeric bounds. The model emits the same `{"name", "arguments"}` shape and
  the same validation rejects mismatched pairs and out-of-range values afterwards.
- **Hosted models think by default.** Thinking tokens are counted in `output_tokens`; compare
  success together with tokens and latency, not success alone.
- **Claude refusals end the episode** (`refusal`). Server-side refusal fallbacks are not
  enabled, because a fallback would hand the episode to a different model mid-run.
- **The v0.4 test pool is public.** A new model's score on it is a post-hoc measurement, not a
  fresh held-out result; the CLI prints this reminder. Use `dev` while tuning anything.

Ollama's OpenAI-compatible `/v1` endpoint does not switch off Qwen3 thinking (as of 0.40),
so the thinking spends the output budget; use the native `ollama:` provider for local models.
