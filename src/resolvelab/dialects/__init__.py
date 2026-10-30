"""Procedurally generated API dialects of the CaseDesk contract (see ``docs/dialects.md``)."""

from .prompt import initial_messages, system_prompt, task_text
from .runner import dialect_actions, run_dialect_episode
from .spec import CANONICAL, Dialect, generate
from .translate import Translator

__all__ = [
    "CANONICAL",
    "Dialect",
    "Translator",
    "dialect_actions",
    "generate",
    "initial_messages",
    "run_dialect_episode",
    "system_prompt",
    "task_text",
]
