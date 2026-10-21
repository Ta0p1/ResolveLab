# Development experiment log

## Initial adapter smoke test

The first `qwen3:4b` smoke test used a generic JSON-schema response wrapper,
ordinary assistant/user messages, thinking requested off, temperature 0 and a
384-token output budget.

On `lost_response`, seed 42, the model repeatedly selected read-only inspection
tools. It consumed all 18 tool steps, made no writes and failed the independent
checker. The raw action trace is preserved in
[`initial-adapter-failure.jsonl`](../artifacts/initial-adapter-failure.jsonl).

This was an integration smoke test, not a complete evaluation of that adapter.
Its result is not used as a baseline improvement claim.

## Native tool protocol

The implementation was changed to Ollama's native function-calling protocol with
assistant/tool history, explicit tool-loop instructions and a larger generation
budget. The model is asked for exactly one tool call per turn. Missing or multiple
calls fail explicitly and retain measured usage.

The release evaluates this configuration across the full public suite. See
[`RESULTS.md`](../artifacts/RESULTS.md) for exact outcomes. The change involved
several factors, so the single smoke test does not isolate the effect of any
individual factor.

The adapter follows the official [Ollama tool-calling protocol](https://docs.ollama.com/capabilities/tool-calling).
Generation settings follow the provider's [thinking controls](https://docs.ollama.com/capabilities/thinking)
and are included in the machine-readable report.

## v0.2 protocol repair and local SFT

The partial-commit failure was traced to a zero-tool-call generation ending at the
output limit. A bounded inference-only retry recovered three tested data seeds;
both attempts' returned token counts remain in the report. This increases the
worst-case generation budget and is documented as an operational tradeoff.

The first actual LoRA experiment uses Qwen3-0.6B on verified scripted actions,
with composition splits frozen before training and checkpoint selection on
development action loss. The full [protocol](post-training.md) and
[result bundle](../artifacts/v0.2/RESULTS.md) distinguish this matched base/SFT
comparison from the historical Ollama integration experiments above.
