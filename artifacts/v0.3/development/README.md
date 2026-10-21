# Development history (excluded from test metrics)

These runs informed integration/prompt choices before the test lock. Initial zero-shot and
unordered one-shot variants are exploratory. Intermediate pre-lock source hashes were
captured from the working tree; those snapshots are not standalone reproducible releases.
The final primary source, data and prompt are committed and locked separately.

`http-base-oneshot-dev` was interrupted after completed cases; its original report retains
the last saved `running` status. Do not treat that partial run as a completed evaluation.
The 4B development probes use CPU-only inference on two development cases; their latency
is not compared with GPU test latency. All original JSON and completed traces are preserved.

| Run | Saved status | Completed episodes | Passed |
|---|---|---:|---:|
| [http-base-dev](http-base-dev.json) | completed | 8 | 0 |
| [http-large-dev](http-large-dev.json) | completed | 8 | 0 |
| [http-base-oneshot-dev](http-base-oneshot-dev.json) | running | 3 | 0 |
| [http-base-ordered-dev](http-base-ordered-dev.json) | completed | 8 | 0 |
| [http-large-ordered-dev](http-large-ordered-dev.json) | completed | 8 | 1 |
| [http-sft-3407-dev](http-sft-3407-dev.json) | completed | 8 | 8 |
| [http-sft-42-dev](http-sft-42-dev.json) | completed | 8 | 8 |
| [http-sft-2026-dev](http-sft-2026-dev.json) | completed | 8 | 8 |
| [http-ollama-cpu-dev](http-ollama-cpu-dev.json) | completed | 2 | 1 |
| [http-ollama-reminder-dev](http-ollama-reminder-dev.json) | completed | 2 | 0 |
