# Contributing to ResolveLab

Install Python 3.11+ and create a virtual environment:

```bash
python -m pip install -c constraints.txt -e ".[dev]"
pytest -q
ruff check .
ruff format --check .
resolvelab eval --seeds 42 73 101 --require-policy reference
python scripts/verify_experiment.py
python scripts/verify_http_study.py
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
unreviewed training datasets. The public `artifacts/v0.2/data` and `artifacts/v0.3/data` are checked,
synthetic export. Regenerate it through the collector, preserve its provenance
and run both executable audit scripts before changing an evidence bundle.

Do not tune on `composition-v1` or `httpdesk-v1` test outcomes and still call them held out.
Introduce a new manifest for future selection. The optional training dependency
environment additionally runs `pytest tests/test_training_loss.py tests/test_http_grammar.py`
to check action-loss equivalence and the actual optional grammar without downloading weights.

The v0.3 audit deliberately checks the frozen Python source, prompt, schema and
data hashes before replay. Do not update a published lock to make changed runtime
code pass. Future runtime work needs a new named experiment; preserve the v0.3
tag and move its historical audit to that checkout when introducing a new version.
Static UI and documentation edits do not change the frozen runtime hash.

Small pull requests with a concrete problem, reproducible behavior and relevant
tests are welcome. Please disclose if a benchmark result follows prompt tuning
on that same suite.
