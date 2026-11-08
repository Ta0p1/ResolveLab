"""Model providers for CaseDesk episodes, chosen by a ``provider:model`` spec.

    teacher                        the scripted runbook (environment check, not a model)
    hf:Qwen/Qwen3-0.6B             local Transformers + the study's constrained decoder (GPU)
    ollama:qwen3:4b                local Ollama, the study's JSON Schema as ``format``
    openai:<model>                 any OpenAI-compatible server (set base_url=...)
    anthropic:claude-opus-5-5      Claude through the Anthropic SDK

Options are ``key=value`` strings passed to the provider (for example ``base_url=...``,
``effort=high``, ``adapter=path/to/lora``). Every provider sees the identical conversation:
the study's system prompt, one-shot demonstration, task, then actions and observations.

The arm is what reports record, so it never holds a local absolute path: a local adapter or
model directory is recorded relative to this checkout when it lies inside it, and otherwise
by its name alone, with the adapter's ``adapter_sha256`` beside it.
"""

import json
from pathlib import Path

from ..packaged import benchmark_file
from ..training import file_hash

STUDY = benchmark_file("casedesk-v2-study.json")
PROVIDERS = ("teacher", "hf", "ollama", "openai", "anthropic")
MAX_TOOLS = 24


def _checkout():
    root = Path(__file__).resolve().parents[3]
    return root if (root / "pyproject.toml").is_file() else None


CHECKOUT = _checkout()  # the checkout this package runs from; None for an installed wheel


def parse_spec(spec):
    provider, _, model = spec.partition(":")
    if provider not in PROVIDERS or (provider != "teacher" and not model):
        raise ValueError(
            f"Unknown model spec {spec!r}; use one of {', '.join(PROVIDERS)} as provider:model"
        )
    return provider, model


def is_local(value):
    """Whether a model or adapter reference is a local path rather than a Hub id."""
    path = Path(value).expanduser()
    return path.is_absolute() or path.exists()


def portable_path(value, root=None):
    """A local path as a report records it: relative to the checkout inside it, else its name.

    Never a drive letter, home directory or user name, so reports can be published as written.
    """
    root = root or CHECKOUT
    path = Path(value).expanduser().resolve()
    if root is not None and path.is_relative_to(root.resolve()):
        return path.relative_to(root.resolve()).as_posix()
    return path.name


def _hf(model, options):
    from ..casedesk.policy import make_policy

    base, _, revision = model.partition("@")
    pinned = {}
    if STUDY.exists():
        study = json.loads(STUDY.read_text(encoding="utf-8"))
        pinned = next((m for m in study["models"].values() if m["base"] == base), {})
    config = {
        "base": base,
        "revision": revision or pinned.get("revision"),
        "max_output": int(options.pop("max_output", 192)),
        "context": int(options.pop("context", 8192)),
        "adapter": options.pop("adapter", None),
    }
    if "thinking" in options:
        config["thinking_budget"] = int(options.pop("thinking"))
        config["sampling_seed"] = int(options.pop("seed", 0))
    arm = dict(config)
    adapter = config["adapter"]
    if adapter is not None:
        local = is_local(adapter)
        # Hashed before the model loads, so a wrong directory fails fast.
        weights = Path(adapter).expanduser() / "adapter_model.safetensors"
        if local and not weights.is_file():
            raise ValueError(f"No adapter_model.safetensors in the adapter directory {adapter}")
        arm["adapter"] = portable_path(adapter) if local else adapter
        arm["adapter_sha256"] = file_hash(weights) if local else None
    policy = make_policy(config, adapter)
    if is_local(base):
        arm["base"] = portable_path(base)
        arm["model"] = arm["base"] + (f"@{revision}" if revision else "")
        arm["name"] = f"hf:{arm['model']}"
        policy.metadata["base"] = arm["base"]
    return policy, arm


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
