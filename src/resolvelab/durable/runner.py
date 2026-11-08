"""Durable episodes: the CaseDesk loop against worker processes that crash and restart.

The loop, budget, prompt and observation format are those of ``casedesk.runner``. Actions come
from ``forced`` first, then a model ``provider``, or else a ``policy`` function of the task
text and observations (the CaseDesk v2 teacher by default). After every request the desk
restarts dead workers and applies the scheduled restart; the episode ends with every worker
killed and the store recovered, and the durable grader judges that recovered state.
"""

import time

from ..casedesk.runner import MAX_TOOLS
from ..casedesk.teacher import teacher_next
from ..httpdesk.schema import append_observation, initial_messages, validate_action
from ..policies import PolicyResponseError
from .desk import DurableAdapter, DurableDesk
from .grading import diagnose_durable, grade_durable


def run_durable_episode(
    spec,
    provider=None,
    *,
    policy=teacher_next,
    forced=(),
    max_tools=MAX_TOOLS,
    store="durable",
    hold_ms=0,
    directory=None,
    prompt=initial_messages,
):
    observations, decisions = [], []
    claim, error = None, None
    started = time.perf_counter()
    with DurableDesk(spec, store=store, hold_ms=hold_ms, directory=directory) as desk:
        adapter = DurableAdapter(desk, duplicate="duplicate_delivery" in spec["faults"])
        messages = prompt(desk.task)
        try:
            for step in range(max_tools):
                usage, seconds, source = {}, 0, "model"
                if step < len(forced):
                    action, source = validate_action(forced[step]), "forced"
                elif provider is None:
                    action, source = policy(desk.task, observations), "policy"
                    if action is None:
                        error = "policy_unrecoverable"
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
                commits_before = desk.commit_count()
                result = adapter.dispatch(action)
                observations.append(
                    {"name": action.name, "arguments": action.arguments, "result": result}
                )
                append_observation(messages, action.name, action.arguments, result)
                if action.name == "finish":
                    claim = action.arguments["outcome"]
                    break
                unanswered = adapter.client.last_worker if result.get("status") == 0 else None
                desk.after_request(commits_before, unanswered)
        finally:
            adapter.close()
    snapshot = desk.snapshot
    if not claim and not error:
        error = "tool_budget"
    return {
        "spec": spec,
        "store": store,
        "workers": desk.workers,
        "task": desk.task,
        "faults": sorted(snapshot.faults),
        "factors": snapshot.factors,
        "verdict": grade_durable(snapshot, claim),
        "diagnostics": diagnose_durable(snapshot, observations, adapter.client.duplicates),
        "error": error,
        "decisions": decisions,
        "observations": observations,
        "http_client": adapter.requests,
        "http_server": snapshot.http_events,
        "duplicates": adapter.client.duplicates,
        "initial_state": snapshot.initial,
        "final_state": snapshot.tickets,
        "commits": snapshot.commits,
        "boots": snapshot.boots,
        "process_faults": snapshot.chaos,
        "wall_seconds": time.perf_counter() - started,
    }
