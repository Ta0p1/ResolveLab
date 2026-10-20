# Contributing to ResolveLab

Install Python 3.11+ and create a virtual environment:

```bash
python -m pip install -e ".[dev]"
pytest -q
ruff check .
ruff format --check .
resolvelab eval --seeds 42 73 101 --require-policy reference
```

Local model evaluation additionally requires Ollama and an installed model.
Unit tests mock the provider only to test error handling and protocol boundaries;
reported local-model benchmarks must come from real inference.

To run the browser checks, install `pip install -e ".[browser]"`, then
`playwright install chromium`. Start an isolated server with
`resolvelab serve --port 8766 --data-dir .local/preview`, and run
`python scripts/browser_smoke.py`. On Windows with Edge installed, you can use
`python scripts/browser_smoke.py --channel msedge` without downloading Chromium.

For a new scenario, document its fault, expected outcome and observable evidence.
Keep hidden fault state out of policy inputs. Include a test that demonstrates
both a correct solution and rejection of a plausible incorrect outcome.

For a new policy, use the same tool budget and checker. Do not read the database,
scenario IDs or fault flags. Distinguish rules from model decisions. Include
model/prompt settings and complete evaluation denominators in any result claim.

Do not commit `.local/`, model weights, private customer data, credentials or
unreviewed training datasets. The example records in this repository are synthetic.

Small pull requests with a concrete problem, reproducible behavior and relevant
tests are welcome. Please disclose if a benchmark result follows prompt tuning
on that same suite.
