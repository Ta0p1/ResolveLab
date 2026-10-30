# Documentation

## Current study (v0.4, CaseDesk v2)

- [Protocol](casedesk-v2-protocol.md): registered questions, arms, decision rules and the one amendment.
- [Results](../artifacts/v0.4/RESULTS.md): test and dev tables, failure taxonomy, data and training, limits.
- [Self-review of v0.3](v0.3-review.md): what was wrong with the previous headline, and the counterfactual.

## The environments

- [CaseDesk as an environment](environment.md): `reset` / `step` / `state`, reward, pools, fidelity tests.
- [API dialects](dialects.md): generated tool contracts over the same service, faults and grader, for
  transfer experiments (environment only, no model results yet), and the
  [draft transfer protocol](dialect-transfer-protocol.md) (not registered).
- [Architecture](architecture.md): the SQLite sync service, the CaseDesk HTTP service and their guarantees.
- [CaseDesk v0.3 protocol](httpdesk-protocol.md) and [model card](httpdesk-model-card.md).
- [Evaluation protocol for the sync service](evaluation.md) and its [model card](model-card.md).

## Earlier studies and project notes

- [Study history](history.md): every study, its question, headline, status and evidence.
- [v0.2 post-training protocol](post-training.md) and [development log](experiments.md).
- [Workbench demo script](demo.md) · [Roadmap](roadmap.md).

## Using the benchmark

- [Evaluate your own model](models.md): `resolvelab casedesk`, providers, options and comparability.
