"""A fault proxy and declarative side-effect grader for any HTTP service.

The proxy runs in front of an unchanged service, injects the faults a scenario declares and
logs every request, fault and response; a read-only probe snapshots the service before and
after; the rule grader reads only the log and the snapshots. See ``docs/fault-proxy-design.md``.

    from resolvelab.proxy import load_scenario, run_episode

    scenario = load_scenario("refund-lost-ack.yaml")
    episode = run_episode(scenario, my_agent, seed=0, log_path="refund.jsonl")
    assert episode.verdict()["passed"]

This package is outside the locked study core: it imports CaseDesk's providers, never the
other way round.
"""

from .episode import AgentClient, Episode, replay, run_episode, serve
from .faults import Fault, Injected
from .grading import GRADER, grade
from .log import Request, Response, read_log
from .matcher import ScenarioError
from .scenario import Scenario, UpstreamRefused, load_scenario

__all__ = [
    "GRADER",
    "AgentClient",
    "Episode",
    "Fault",
    "Injected",
    "Request",
    "Response",
    "Scenario",
    "ScenarioError",
    "UpstreamRefused",
    "grade",
    "load_scenario",
    "read_log",
    "replay",
    "run_episode",
    "serve",
]
