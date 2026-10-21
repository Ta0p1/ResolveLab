# Experiment provenance

The v0.1 release artifacts are unchanged. These experiments progressed through
separately recorded code states; their hashes are not retroactively rewritten to
match the final release.

| Stage | Source state | Package Python SHA-256 |
|---|---|---|
| Targeted 4B partial-commit regression | `e820221` plus `partial-recovery-source.patch` | `6c36a5edab875e2d88ab7b6af06d55ac8168524e818cb27a452ede1a96d97431` |
| LoRA training launch | `ad7f12f` | `630ff3ea137b2a1b27b949d71a0d84617be51e69843ca1f836a1c8af3033bba2` |
| Pre-specified strict base/SFT test | `f707ae1` | `b880c925fffa5e87d3d094009fc1418428eb12eeb767b65040da1833985fa97c` |
| Exploratory outer-code-fence control | `c3a0dd4` | `b6772564546198d7437d10dcb4335be8e5295c60a72dd8410748c453262bf415` |

`source_fingerprint()` hashes package Python filenames and contents in sorted
order. Static presentation and repository documentation are outside this hash.
The partial-regression patch is supplied because that run preceded the first
combined training commit; its reconstructed source hash was checked explicitly.

Training config SHA-256:
`7276e44c2479ec44d62aa064fe178e161bdba71656661d802623dc8cd79c6f50`.
Manifest canonical JSON SHA-256:
`f7811a869f67e5374ee8333e1359456de856c078c306b9ada5ea30efdcf1076c`.
Base model revision:
`Qwen/Qwen3-0.6B@c1899de289a04d12100db370d81485cdf75e47ca`.
Selected adapter SHA-256:
`e99f1065100c969f54e00ad3c4c0ea1cc2e9b4e32524fc194bb3bfb8b78bc8b5`.

The raw training JSONL used Windows CRLF. `training.json` preserves those original
file hashes under `data_sha256`; portable LF exports are identified separately by
`portable_data_sha256`. The data content and ordering are unchanged. The collector
now writes LF on all platforms. Replaying tools and comparing structured outcomes
does not depend on text-file newline conventions.

Training used the pinned PyTorch/Transformers/PEFT dependencies in
`training-environment.txt`. No remote model API, paid training service, external
customer data or private job-application material was used.
