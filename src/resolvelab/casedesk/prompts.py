"""Prompt construction with an explicit in-context demonstration.

``prompt_with_demo(load_v03_demo())`` reproduces ``httpdesk.schema.initial_messages`` exactly
(checked by test); other demos let diagnostics vary the example without touching v0.3 code.
"""

import json
from pathlib import Path

from ..httpdesk.schema import ARGUMENTS, DESCRIPTIONS, SYSTEM, action_json
from ..store import dumps
from .runner import run_episode

V03_DEMO = Path(__file__).resolve().parents[1] / "httpdesk" / "demo.json"


def load_v03_demo():
    return json.loads(V03_DEMO.read_text(encoding="utf-8"))["messages"]


def build_demo(state):
    """A verified teacher conversation in the exact v0.3 demo format."""
    trace = run_episode(None, state=state)
    if not trace["verdict"]["passed"]:
        raise ValueError("Demonstration episode failed")
    messages = [{"role": "user", "content": trace["task"]}]
    for obs in trace["observations"]:
        messages.append(
            {
                "role": "assistant",
                "content": action_json({"name": obs["name"], "arguments": obs["arguments"]}),
            }
        )
        if obs["name"] != "finish":
            messages.append(
                {"role": "user", "content": dumps({"tool": obs["name"], "result": obs["result"]})}
            )
    return messages


def prompt_with_demo(*demos):
    catalog = [
        {"name": name, "description": DESCRIPTIONS[name], "parameters": cls.model_json_schema()}
        for name, cls in ARGUMENTS.items()
    ]

    def initial(task):
        return [
            {"role": "system", "content": SYSTEM + "\nTools:\n" + json.dumps(catalog)},
            *[m for demo in demos for m in demo],
            {"role": "user", "content": "New independent task:\n" + task},
        ]

    return initial
