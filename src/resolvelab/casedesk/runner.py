"""Real-socket episodes for v2 worlds: forced prefixes, teacher continuation, model policies."""

import copy
import time

from ..httpdesk.adapter import DeskAdapter
from ..httpdesk.schema import action_json, append_observation, initial_messages, validate_action
from ..httpdesk.service import DeskServer
from ..policies import PolicyResponseError
from .grading import diagnose, grade_v2
from .teacher import teacher_next
from .world import WorldState

MAX_TOOLS = 24


def run_episode(
    spec,
    provider=None,
    *,
    max_tools=MAX_TOOLS,
    forced=(),
    state=None,
    prompt=initial_messages,
    keep_messages=False,
):
    """Run one episode. Actions come from ``forced`` first, then the provider (or the teacher).

    With ``keep_messages`` every step stores the exact conversation the policy saw, which is
    what imitation rows are built from.
    """
    state = state or WorldState(spec)
    messages = prompt(state.task)
    observations, decisions, steps = [], [], []
    claim, error = None, None
    started = time.perf_counter()
    with DeskServer(state) as server:
        adapter = DeskAdapter(server.url)
        try:
            for step in range(max_tools):
                usage, seconds, source = {}, 0, "model"
                if step < len(forced):
                    action, source = validate_action(forced[step]), "forced"
                elif provider is None:
                    action, source = teacher_next(state.task, observations), "teacher"
                    if action is None:
                        error = "teacher_unrecoverable"
                        break
                else:
                    try:
                        action, usage, seconds = provider.next(messages)
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
                decisions.append(
                    {
                        "step": step,
                        "source": source,
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
                append_observation(messages, action.name, action.arguments, result)
                if action.name == "finish":
                    claim = action.arguments["outcome"]
                    break
        finally:
            adapter.close()
    if not claim and not error:
        error = "tool_budget"
    return {
        "spec": spec,
        "task": state.task,
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


def actions_of(trace):
    return [d["action"] for d in trace["decisions"] if "action" in d]


def label_state(spec, prefix, budget=2 * MAX_TOOLS):
    """Teacher label at the state reached by ``prefix``, verified by finishing with the teacher.

    Returns (label, verified, continuation_steps). A label is usable only if the teacher's
    continuation from exactly this state passes the independent grader. The budget is larger
    than the evaluation budget: a correct action stays correct even after a wasteful prefix.
    """
    trace = run_episode(spec, max_tools=budget, forced=prefix)
    actions = actions_of(trace)
    if len(actions) <= len(prefix):
        return None, False, 0
    if actions[: len(prefix)] != [validate_action(a).model_dump() for a in prefix]:
        raise RuntimeError("Replay diverged from the recorded prefix")
    return actions[len(prefix)], trace["verdict"]["passed"], len(actions) - len(prefix)


def target_text(action):
    return action_json(action)
