"""The fault engine: every agent request of an episode goes through ``Proxy.handle``.

For each request, in order: log it; show it to each fault's ``before`` hook (the first
``Injected`` answers it); then ``instead``; otherwise forward it to the service; then the
``after`` hooks, which may replace the response; then every fault ``observe``s what the
agent receives, and that is logged. Requests are handled one at a time, so the log order is
the order the service saw.

Two control endpoints live under the scenario's ``control_prefix`` (``/_resolvelab``) and
are never forwarded:

- ``POST /_resolvelab/wait`` with ``{"seconds": n}`` advances the virtual clock. Rate limits
  read this clock, so waiting is deterministic and instant. A service with a wait endpoint
  of its own names it in the scenario's ``clock``; that request is forwarded and, when the
  service answers 2xx, moves the clock by its body's seconds as well (a ``clock`` record).
- ``POST /_resolvelab/finish`` with ``{"outcome": "resolved" | "escalated", "summary": ...}``
  records the agent's claim and ends the episode; later requests get 409.

``GET /_resolvelab/task`` returns the task text, for agents in their own process.
"""

import json
import threading

import httpx

from .log import UNLOGGED, Request, Response, encode_body, logged_headers
from .matcher import json_body, lookup
from .scenario import OUTCOMES

MAX_WAIT = 3600


class Proxy:
    def __init__(self, scenario, seed, log, client):
        self.scenario, self.seed, self.log, self.client = scenario, seed, log, client
        self.faults = scenario.faults(seed)
        self.clock = 0  # virtual seconds
        self.seq = 0
        self.claim = None
        self.finished = threading.Event()
        self.lock = threading.RLock()

    # -- agent requests -----------------------------------------------------------------

    def handle(self, request):
        prefix = self.scenario.control_prefix
        if request.path == prefix or request.path.startswith(prefix + "/"):
            return self.control(request, request.path[len(prefix) :])
        with self.lock:
            if self.finished.is_set():
                return Response.json(409, {"error": "episode_finished"})
            self.seq += 1
            seq = self.seq
            self.log.write(self.record("request", seq, request, clock=self.clock))
            response = self.inject(seq, "before", lambda f: f.before(request, self))
            if response is None:
                response = self.inject(seq, "instead", lambda f: f.instead(request, self))
            if response is None:
                response, reached = self.forward(seq, request)
                if reached:
                    self.advance(seq, request, response)
                    for fault in self.faults:
                        injected = fault.after(request, response, self)
                        if injected is not None:
                            self.note(seq, fault, "after", injected)
                            response = injected.response
            for fault in self.faults:
                fault.observe(request, response, self)
            self.log.write(self.record("response", seq, response, status=response.status))
            return response

    def inject(self, seq, stage, hook):
        for fault in self.faults:
            injected = hook(fault)
            if injected is not None:
                self.note(seq, fault, stage, injected)
                return injected.response
        return None

    def note(self, seq, fault, stage, injected):
        self.log.write(
            {
                "type": "fault",
                "seq": seq,
                "fault": fault.index,
                "kind": fault.kind,
                "stage": stage,
                "status": injected.response.status,
                "detail": injected.detail,
            }
        )

    def forward(self, seq, request):
        """(response, reached): the service's answer, or a 502 when it could not be reached."""
        headers = {k: v for k, v in request.headers.items() if k not in UNLOGGED}
        headers["accept-encoding"] = "identity"
        try:
            answer = self.client.request(
                request.method,
                self.scenario.upstream + request.target,
                headers=headers,
                content=request.body,
            )
        except httpx.HTTPError as exc:
            self.log.write({"type": "upstream", "seq": seq, "error": type(exc).__name__})
            return Response.json(502, {"error": "upstream_unreachable"}), False
        kept = {}
        for name, value in answer.headers.multi_items():
            name = name.lower()
            if name not in UNLOGGED:
                kept[name] = f"{kept[name]}, {value}" if name in kept else value
        location = kept.get("location", "")
        if location.startswith(self.scenario.upstream + "/"):
            # A redirect to the service itself must not lead the agent around the proxy.
            kept["location"] = location[len(self.scenario.upstream) :]
        response = Response(answer.status_code, kept, answer.content)
        self.log.write(self.record("upstream", seq, response, status=response.status))
        return response, True

    def advance(self, seq, request, upstream):
        """The scenario's ``clock`` request, answered 2xx by the service, moves the clock too."""
        spec = self.scenario.clock_request
        if spec is None or not 200 <= upstream.status < 300 or spec.matcher.match(request) is None:
            return
        found, seconds = lookup(json_body(request.body), spec.field)
        if not found or isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
            return
        self.clock += seconds
        self.log.write({"type": "clock", "seq": seq, "seconds": seconds, "clock": self.clock})

    def record(self, kind, seq, message, **fields):
        record = {"type": kind, "seq": seq, **fields}
        if isinstance(message, Request):
            record |= {"method": message.method, "path": message.path, "query": message.query}
        record["headers"] = logged_headers(message.headers, self.scenario.redact)
        return record | encode_body(message.body)

    # -- control ------------------------------------------------------------------------

    def wait(self, seconds):
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= MAX_WAIT:
            raise ValueError(f"seconds must be an integer from 1 to {MAX_WAIT}")
        with self.lock:
            if self.finished.is_set():
                raise RuntimeError("The episode has finished")
            self.clock += seconds
            self.log.write({"type": "wait", "seconds": seconds, "clock": self.clock})
            return self.clock

    def finish(self, outcome, summary=""):
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}")
        if not isinstance(summary, str):
            raise ValueError("summary must be a string")
        with self.lock:
            if self.finished.is_set():
                raise RuntimeError("The episode has finished")
            self.claim = {"outcome": outcome, "summary": summary}
            self.log.write({"type": "finish", "outcome": outcome, "summary": summary})
            self.finished.set()

    def control(self, request, action):
        try:
            if request.method == "GET" and action == "/task":
                return Response.json(200, {"task": self.scenario.task, "api": self.scenario.api})
            if request.method != "POST" or action not in ("/wait", "/finish"):
                return Response.json(404, {"error": "unknown_control_endpoint"})
            body = json.loads(request.body or b"{}")
            if not isinstance(body, dict):
                raise ValueError("expected a JSON object")
            if action == "/wait":
                return Response.json(200, {"clock": self.wait(body.get("seconds"))})
            self.finish(body.get("outcome"), body.get("summary", ""))
            return Response.json(200, {"finished": True})
        except RuntimeError as exc:
            return Response.json(409, {"error": "episode_finished", "detail": str(exc)})
        except ValueError as exc:
            return Response.json(400, {"error": "bad_request", "detail": str(exc)})
