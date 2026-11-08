# Contributing to ResolveLab

Install Python 3.11+ and create a virtual environment:

```bash
python -m pip install -c constraints.txt -e ".[dev]"
pytest -q
ruff check .
ruff format --check .
resolvelab eval --seeds 42 73 101 --require-policy reference
python examples/casedesk_quickstart.py
python scripts/verify_experiment.py
python scripts/verify_http_study.py
python scripts/verify_casedesk_v2.py --dagger-every 20 --replay-every 10
python scripts/verify_dialect_transfer.py --dagger-every 20 --replay-every 10
python scripts/check_proxy_parity.py --every 10                 # the fault proxy against grader v2
```

Optionally `pip install pre-commit && pre-commit install` to run ruff (pinned to CI's version)
and YAML/TOML checks on every commit. Pull requests use a checklist of the evidence rules
below; reports that a grader accepts a bad episode are especially welcome (see the "Grader or
result concern" issue form). Security issues go through [SECURITY.md](SECURITY.md).

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

Do not tune on `composition-v1`, `httpdesk-v1` or `casedesk-v2` test outcomes and still call
them held out.
Introduce a new manifest for future selection. The optional training dependency
environment additionally runs `pytest tests/test_training_loss.py tests/test_http_grammar.py`
to check action-loss equivalence and the actual optional grammar without downloading weights.

Each audit checks its own locked source files, prompt, schema and data hashes before replay, and
replays on the locked source rather than on `src/`. `scripts/locked_source.py` reads
`artifacts/locked-source/<study>.zip`, refuses it unless it reproduces the source hash in that
study's lock, and re-runs the audit in a process that can import nothing else from the package.

`src/` is held to a narrower rule. It must match the snapshots, apart from the `__version__` line
and the files in `OUTSIDE_CORE`: `providers/`, `main.py`, `__main__.py`, `cli.py`, `api.py`,
`casedesk/cli.py` and `casedesk/env.py`. No script imports those files, directly or through the
study code, and `tests/test_locked_source.py` walks the imports to keep it so. They can be
maintained, and the audit names any that differ. An edit to any other locked file fails CI. Do not
edit those files or update a published lock or snapshot to make changed code pass. New runtime work
goes into new modules under a new named experiment, which keeps every earlier audit green. A new
study's lock also needs a snapshot (`scripts/snapshot_locked_source.py`). Static UI, scripts and
documentation edits do not change the locked hashes.

Re-running a test phase still needs the exact source: `scripts/dialect_transfer.py` refuses any
tree whose whole-package hash differs from the lock, so check out the lock's commit first.

Small pull requests with a concrete problem, reproducible behavior and relevant
tests are welcome. Please disclose if a benchmark result follows prompt tuning
on that same suite.
