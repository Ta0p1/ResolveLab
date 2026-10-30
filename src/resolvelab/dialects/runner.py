"""Real-socket CaseDesk episodes in a dialect.

Mirrors ``casedesk.runner.run_episode``: the same WorldState, HTTP service, fault injection,
teacher and grader. The policy reads and writes only the dialect; each action is validated
against the dialect's schema, translated, dispatched, and its result translated back. The
trace keeps the canonical observations, so ``grade_v2``, ``diagnose`` and the teacher see
exactly what they see in the study, and ``dialect_actions`` records what the policy wrote.
"""

import copy
import time

from ..casedesk.grading import diagnose, grade_v2
from ..casedesk.runner import MAX_TOOLS
from ..casedesk.teacher import teacher_next
from ..casedesk.world import WorldState
from ..httpdesk.adapter import DeskAdapter
from ..httpdesk.schema import validate_action
from ..httpdesk.service import DeskServer
from ..policies import PolicyResponseError
from .prompt import initial_messages, observation_text, task_text
from .translate import Translator


def dialect_task(dialect, spec, state):
    return task_text(dialect, spec["phrasing"], state.reference, state.desired)


def run_dialect_episode(
    spec, dialect, policy=None, *, max_tools=MAX_TOOLS, forced=(), state=None, keep_messages=False
):
    """Run one episode. Actions come from ``forced`` first, then ``policy`` (or the teacher).

    ``forced`` and the policy produce dialect actions (``{"name", "arguments"}`` dicts); the
    policy is any object whose ``next(messages)`` returns ``(action, usage, seconds)``. The
    teacher plans on canonical observations and its action is rendered into the dialect.
    """
    state = state or WorldState(spec)
    translator = Translator(dialect, seed=spec["id"])
    task = dialect_task(dialect, spec, state)
    messages = initial_messages(dialect, task)
    observations, decisions, steps = [], [], []
    claim, error = None, None
    started = time.perf_counter()
    with DeskServer(state) as server:
        adapter = DeskAdapter(server.url)
        try:
            for step in range(max_tools):
                usage, seconds, source = {}, 0, "model"
                if step < len(forced):
                    written, source = forced[step], "forced"
                elif policy is None:
                    planned, source = teacher_next(state.task, observations), "teacher"
                    if planned is None:
                        error = "teacher_unrecoverable"
                        break
                    written = translator.from_canonical(planned.model_dump())
                else:
                    try:
                        written, usage, seconds = policy.next(messages)
                    except PolicyResponseError as exc:
                        decisions.append(
                            {"step": step, "error": str(exc), "usage": exc.usage, "seconds": exc.seconds}
                        )
                        error = exc.usage.get("failure_category", "protocol_error")
                        break
                    except Exception as exc:
                        decisions.append(
                            {"step": step, "error": f"{type(exc).__name__}: {exc}", "usage": {}}
                        )
                        error = "inference_error"
                        break
                written = written.model_dump() if hasattr(written, "model_dump") else written
                try:
                    action = validate_action(translator.to_canonical(written))
                except ValueError as exc:
                    decisions.append(
                        {
                            "step": step,
                            "error": f"invalid_action: {exc}",
                            "written": written,
                            "usage": usage,
                        }
                    )
                    error = "invalid_action"
                    break
                decisions.append(
                    {
                        "step": step,
                        "source": source,
                        "written": written,
                        "action": action.model_dump(),
                        "usage": usage,
                        "seconds": seconds,
                    }
                )
                if keep_messages:
                    steps.append({"step": step, "messages": copy.deepcopy(messages)})
                result = adapter.dispatch(action)
                observations.append(
                    {"name": action.name, "arguments": action.arguments, "result": result}
                )
                messages.extend(
                    [
                        {"role": "assistant", "content": translator.action_text(written)},
                        {
                            "role": "user",
                            "content": observation_text(dialect, translator, action.name, result),
                        },
                    ]
                )
                if action.name == "finish":
                    claim = action.arguments["outcome"]
                    break
        finally:
            adapter.close()
    if not claim and not error:
        error = "tool_budget"
    return {
        "spec": spec,
        "dialect": dialect.describe(),
        "task": state.task,
        "dialect_task": task,
        "faults": sorted(state.faults),
        "factors": getattr(state, "factors", None),
        "verdict": grade_v2(state, claim),
        "diagnostics": diagnose(state, observations),
        "error": error,
        "decisions": decisions,
        "observations": observations,
        "http_client": adapter.requests,
        "http_server": state.http_events,
        "initial_state": state.initial,
        "final_state": state.tickets,
        "commits": state.commits,
        "wall_seconds": time.perf_counter() - started,
        "steps": steps,
    }


def dialect_actions(trace):
    return [d["written"] for d in trace["decisions"] if "written" in d and "action" in d]
