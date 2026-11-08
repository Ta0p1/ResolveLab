"""One episode: the before probe, the agent's requests through the proxy, the after probe.

    scenario = load_scenario("refund-lost-ack.yaml")
    episode = run_episode(scenario, agent, seed=0, log_path="refund.jsonl")
    episode.verdict()["passed"]

``agent(client, task)`` gets an ``AgentClient``: an ``httpx.Client`` whose base URL is the
proxy, plus ``wait(seconds)`` and ``finish(outcome, summary)``. ``serve`` runs the same
episode for an agent in another process, and ``replay`` re-runs a logged one.
"""

import httpx

from .. import __version__
from .engine import Proxy
from .grading import GRADER, grade
from .log import FORMAT, REDACTED, EpisodeLog, Request, decode_body, read_log
from .probe import take
from .scenario import Scenario
from .server import ProxyServer


class Episode:
    def __init__(self, scenario, *, seed=0, log_path=None, transport=None):
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        self.scenario, self.seed = scenario, seed
        self.log = EpisodeLog(log_path)
        options = {"timeout": scenario.timeout, "trust_env": False, "transport": transport}
        self.client = httpx.Client(follow_redirects=False, **options)
        self.probe_client = httpx.Client(base_url=scenario.upstream, **options)
        self.proxy, self.ended = None, False

    @property
    def records(self):
        return self.log.records

    def start(self):
        try:
            self.log.write(
                {
                    "type": "header",
                    "format": FORMAT,
                    "scenario": self.scenario.data,
                    "scenario_sha256": self.scenario.sha256,
                    "seed": self.seed,
                    "grader": GRADER,
                    "resolvelab": __version__,
                }
            )
            before = take(self.scenario, self.probe_client)
            failed = next((r for r in before if "error" in r), None)
            if failed is not None:
                raise RuntimeError(
                    f"The state probe could not read {self.scenario.upstream}{failed['get']}: "
                    f"{failed['error']}"
                )
            self.log.write({"type": "probe", "phase": "before", "responses": before})
            self.proxy = Proxy(self.scenario, self.seed, self.log, self.client)
        except BaseException:
            self.ended = True
            self.close()
            raise
        return self

    def close(self):
        self.client.close()
        self.probe_client.close()
        self.log.close()

    def stop(self, reason=None):
        """Refuse further requests, take the after probe and close the log."""
        if self.ended:
            return
        self.ended = True
        try:
            with self.proxy.lock:
                self.proxy.finished.set()
                reason = reason or ("finish" if self.proxy.claim else "stopped")
                after = take(self.scenario, self.probe_client)
                self.log.write({"type": "probe", "phase": "after", "responses": after})
                self.log.write({"type": "end", "reason": reason})
        finally:
            self.close()

    def verdict(self):
        return grade(self.records)

    def __enter__(self):
        return self.start()

    def __exit__(self, kind, *_):
        self.stop("error" if kind is not None else None)


class AgentClient(httpx.Client):
    """An HTTP client pointed at the proxy, with the episode's control endpoints."""

    def __init__(self, proxy_url, control_prefix="/_resolvelab", **kwargs):
        kwargs.setdefault("timeout", 60)
        super().__init__(base_url=proxy_url, trust_env=False, **kwargs)
        self.control_prefix = control_prefix

    def wait(self, seconds):
        response = self.post(f"{self.control_prefix}/wait", json={"seconds": seconds})
        response.raise_for_status()
        return response.json()["clock"]

    def finish(self, outcome, summary=""):
        response = self.post(
            f"{self.control_prefix}/finish", json={"outcome": outcome, "summary": summary}
        )
        response.raise_for_status()

    def task(self):
        return self.get(f"{self.control_prefix}/task").json()["task"]


def run_episode(scenario, agent, *, seed=0, log_path=None, transport=None):
    """Run ``agent(client, task)`` through the proxy over real HTTP; returns the Episode."""
    episode = Episode(scenario, seed=seed, log_path=log_path, transport=transport).start()
    reason = None
    try:
        with ProxyServer(episode.proxy) as server:
            with AgentClient(server.url, scenario.control_prefix) as client:
                agent(client, scenario.task)
    except BaseException:
        reason = "error"
        raise
    finally:
        episode.stop(reason)
    return episode


def serve(scenario, *, seed=0, log_path=None, host="127.0.0.1", port=0, ready=None, stop=None):
    """Serve one episode until the agent finishes, ``stop`` is set or Ctrl-C."""
    episode = Episode(scenario, seed=seed, log_path=log_path).start()
    reason = None
    try:
        with ProxyServer(episode.proxy, host, port) as server:
            if ready is not None:
                ready(server.url)
            while not episode.proxy.finished.wait(0.2):
                if stop is not None and stop.is_set():
                    reason = "stopped"
                    break
    except KeyboardInterrupt:
        reason = "stopped"
    finally:
        episode.stop(reason)
    return episode


def replay(source, *, upstream=None, headers=None, transport=None):
    """Re-send a logged episode's requests, waits and claim through a fresh proxy.

    The service has to start from the state the log started from. Every record except the
    requests themselves (the input) is compared: probes, faults, the service's answers and
    the responses the agent received. ``headers`` supplies values for redacted headers;
    without them a redacted header is not sent.
    """
    records = read_log(source)
    header = records[0]
    scenario = Scenario(header["scenario"])
    if upstream:
        scenario = scenario.with_overrides(upstream=upstream)
    supplied = {k.lower(): v for k, v in (headers or {}).items()}
    episode = Episode(scenario, seed=header["seed"], transport=transport).start()
    end = None
    try:
        for record in records[1:]:
            if record["type"] == "request":
                sent = {}
                for name, value in record["headers"].items():
                    if value != REDACTED:
                        sent[name] = value
                    elif name in supplied:
                        sent[name] = supplied[name]
                episode.proxy.handle(
                    Request(
                        record["method"],
                        record["path"],
                        record.get("query", ""),
                        sent,
                        decode_body(record),
                    )
                )
            elif record["type"] == "wait":
                episode.proxy.wait(record["seconds"])
            elif record["type"] == "finish":
                episode.proxy.finish(record["outcome"], record.get("summary", ""))
            elif record["type"] == "end":
                end = record["reason"]
    finally:
        episode.stop(end)
    logged = [r for r in records[1:] if r["type"] != "request"]
    replayed = [r for r in episode.records[1:] if r["type"] != "request"]
    mismatches = [
        {"index": i, "logged": a, "replayed": b}
        for i, (a, b) in enumerate(zip(logged, replayed))
        if a != b
    ]
    if len(logged) != len(replayed):
        mismatches.append(
            {
                "index": min(len(logged), len(replayed)),
                "logged_records": len(logged),
                "replayed_records": len(replayed),
            }
        )
    return {
        "identical": not mismatches,
        "mismatches": mismatches[:10],
        "verdict": grade(episode.records),
        "logged_verdict": grade(records),
        "records": episode.records,
    }
