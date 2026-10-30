"""Model providers for CaseDesk episodes, chosen by a ``provider:model`` spec.

    teacher                        the scripted runbook (environment check, not a model)
    hf:Qwen/Qwen3-0.6B             local Transformers + the study's constrained decoder (GPU)
    ollama:qwen3:4b                local Ollama, the study's JSON Schema as ``format``
    openai:<model>                 any OpenAI-compatible server (set base_url=...)
    anthropic:claude-opus-5-5      Claude through the Anthropic SDK

Options are ``key=value`` strings passed to the provider (for example ``base_url=...``,
``effort=high``, ``adapter=path/to/lora``). Every provider sees the identical conversation:
the study's system prompt, one-shot demonstration, task, then actions and observations.
"""

import json
from pathlib import Path

STUDY = Path(__file__).resolve().parents[3] / "benchmarks/casedesk-v2-study.json"
PROVIDERS = ("teacher", "hf", "ollama", "openai", "anthropic")
MAX_TOOLS = 24


def parse_spec(spec):
    provider, _, model = spec.partition(":")
    if provider not in PROVIDERS or (provider != "teacher" and not model):
        raise ValueError(
            f"Unknown model spec {spec!r}; use one of {', '.join(PROVIDERS)} as provider:model"
        )
    return provider, model


def _hf(model, options):
    from ..casedesk.policy import make_policy

    base, _, revision = model.partition("@")
    pinned = {}
    if STUDY.exists():
        study = json.loads(STUDY.read_text(encoding="utf-8"))
        pinned = next((m for m in study["models"].values() if m["base"] == base), {})
    arm = {
        "base": base,
        "revision": revision or pinned.get("revision"),
        "max_output": int(options.pop("max_output", 192)),
        "context": int(options.pop("context", 8192)),
        "adapter": options.pop("adapter", None),
    }
    if "thinking" in options:
        arm["thinking_budget"] = int(options.pop("thinking"))
        arm["sampling_seed"] = int(options.pop("seed", 0))
    return make_policy(arm, arm["adapter"]), arm


def make_provider(spec, options=None):
    """(provider or None for the teacher, arm description recorded in reports)."""
    provider, model = parse_spec(spec)
    options = dict(options or {})
    arm = {"name": spec, "provider": provider, "model": model or None, "max_tools": MAX_TOOLS}
    if provider == "teacher":
        instance = None
    elif provider == "hf":
        instance, details = _hf(model, options)
        arm |= details
    elif provider == "ollama":
        from .ollama import OllamaProvider

        instance = OllamaProvider(model, **options)
    elif provider == "openai":
        from .openai_compat import OpenAICompatibleProvider

        instance = OpenAICompatibleProvider(model, **options)
    else:
        from .anthropic import AnthropicProvider

        instance = AnthropicProvider(model, **options)
    if options and provider in ("teacher", "hf"):
        raise ValueError(f"Unused options for {provider}: {sorted(options)}")
    arm["options"] = {k: str(v) for k, v in sorted(options.items())}
    return instance, arm
