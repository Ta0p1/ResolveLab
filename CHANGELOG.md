# Changelog

## 0.2.0 — 2026-10-21

- Recover a zero-tool-call generation cutoff with one bounded inference retry;
  retain usage from both attempts and preserve the original failed episode.
- Freeze disjoint train/dev/test compositions and validate training provenance.
- Add optional Transformers/PEFT inference and action-only LoRA training with
  development-loss checkpoint selection, weight hashes and memory measurements.
- Publish the actual local 0.6B experiment: 528 supervised actions, 24/24 SFT
  test passes, original strict-parser comparison and an exploratory code-fence
  control. Explicitly document baseline protocol failures and limited scope.
- Re-execute all 120 published test tool trajectories without a GPU to audit
  outcomes, alongside split, metric and adapter-selection checks.
- Add a Post-training view, model card, reproduction commands, updated demo and
  resume material; keep all v0.1 evidence intact.

## 0.1.0 — Initial executable baseline

Local workbench, Ollama native tools, transactional sync sandbox, independent SQL
outcomes, durable traces and public development measurements.
