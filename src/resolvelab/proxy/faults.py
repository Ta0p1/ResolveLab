"""Faults: each one changes the correct next action, and each is deterministic.

A fault implements up to four hooks. The engine calls them in scenario order:

- ``before(request, env)`` before forwarding. Returning an ``Injected`` answers the request;
  it is not forwarded and later faults do not see it.
- ``instead(request, env)`` in place of forwarding (no milestone-1 fault uses it yet).
- ``after(request, response, env)`` after the service answered; an ``Injected`` replaces
  the response the agent receives. Later faults see the replacement.
- ``observe(request, response, env)`` with what the agent finally received, for every
  request; bookkeeping only.

``env`` exposes the virtual ``clock`` (seconds). A fault matches through its own
``Selector``, so its occurrence counts only the requests it was shown. Randomness comes from
a generator seeded by the episode seed and the fault's position, never from the wall clock.
"""

import random
from dataclasses import dataclass

from .log import Response
from .matcher import PLACEHOLDER, WRITE, ScenarioError, parse_selector

LATER = ("concurrent_write", "stale_read", "partial_page", "injected_text", "timeout")


@dataclass
class Injected:
    """A response a fault puts in front of the agent, with what to log about it."""

    response: Response
    detail: dict


class Fault:
    kind = ""
    statuses = range(400, 600)
    default_status = 500
    default_body = None
    methods = None  # default match methods
    allowed = None  # methods the fault may apply to at all
    occurrence = 1  # default occurrence
    keys = frozenset({"kind", "match", "response"})

    def __init__(self, index, spec, render, seed):
        where = f"faults[{index}] ({self.kind})"
        unknown = set(spec) - self.keys
        if unknown:
            raise ScenarioError(f"{where}: unknown key(s) {sorted(unknown)}")
        self.index, self.where = index, where
        self.selector = parse_selector(
            spec.get("match"),
            f"{where}.match",
            render,
            methods=self.methods,
            occurrence=self.occurrence,
            allowed=self.allowed,
        )
        self.rng = random.Random(f"resolvelab-proxy:{seed}:{index}:{self.kind}")
        response = spec.get("response") or {}
        if not isinstance(response, dict) or set(response) - {"status", "body", "headers"}:
            raise ScenarioError(f"{where}: response takes status, body and headers")
        self.status = response.get("status", self.default_status)
        if self.status not in self.statuses:
            allowed = self.statuses
            allowed = f"{allowed[0]}-{allowed[-1]}" if isinstance(allowed, range) else list(allowed)
            raise ScenarioError(f"{where}: status must be in {allowed}")
        self.body = response.get("body")  # None: the fault's own default
        headers = response.get("headers") or {}
        if not isinstance(headers, dict):
            raise ScenarioError(f"{where}: response headers must be a mapping")
        self.headers = {str(k).lower(): str(v) for k, v in headers.items()}

    def respond(self, detail, default=None, headers=None):
        body = self.body if self.body is not None else default or self.default_body or {}
        return Injected(Response.json(self.status, body, {**self.headers, **(headers or {})}), detail)

    def before(self, request, env):
        return None

    def instead(self, request, env):
        return None

    def after(self, request, response, env):
        return None

    def observe(self, request, response, env):
        return None


class RateLimit(Fault):
    """429 with ``Retry-After``; requests before the virtual clock reaches it get 429 again."""

    kind = "rate_limit"
    statuses = (429, 503)
    default_status = 429
    keys = Fault.keys | {"retry_after"}

    def __init__(self, index, spec, render, seed):
        super().__init__(index, spec, render, seed)
        value = spec.get("retry_after", 2)
        bounds = value if isinstance(value, list) else [value, value]
        if (
            len(bounds) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in bounds)
            or not 1 <= bounds[0] <= bounds[1] <= 3600
        ):
            raise ScenarioError(f"{self.where}: retry_after is seconds (1-3600) or a [min, max] range")
        self.bounds = tuple(bounds)
        self.until = None  # virtual time the current window ends

    def limited(self, seconds, reason):
        return self.respond(
            {"reason": reason, "retry_after": seconds},
            {"error": "rate_limited", "retry_after": seconds},
            {"retry-after": str(seconds)},
        )

    def before(self, request, env):
        matched, selected, _ = self.selector.see(request)
        if matched and self.until is not None and env.clock < self.until:
            return self.limited(self.until - env.clock, "window")
        if selected:
            seconds = self.rng.randint(*self.bounds)
            self.until = env.clock + seconds
            return self.limited(seconds, "fired")
        return None


class Precondition(Fault):
    """412 (or 409) on a matching write; that path keeps failing until the agent re-reads.

    ``reread`` names the read that clears it (default: GET of the write's own path). Any
    placeholder in it must be bound by the match path, e.g. ``/orders/{id}`` for
    ``/orders/{id}/address``. Only a 2xx GET the agent received counts as a re-read.
    """

    kind = "precondition"
    statuses = (409, 412)
    default_status = 412
    default_body = {"error": "precondition_failed"}
    methods = WRITE
    allowed = WRITE
    keys = Fault.keys | {"reread"}

    def __init__(self, index, spec, render, seed):
        super().__init__(index, spec, render, seed)
        self.reread = spec.get("reread")
        if self.reread is not None:
            self.reread = render(self.reread, f"{self.where}.reread", wildcards=True)
            template = self.selector.matcher.template or ""
            bound = set(PLACEHOLDER.findall(template))
            free = set(PLACEHOLDER.findall(self.reread)) - bound
            if free:
                raise ScenarioError(
                    f"{self.where}: reread placeholder(s) {sorted(free)} are not bound by the match path"
                )
        self.pending = {}  # write path -> the read path that clears it

    def before(self, request, env):
        if request.method in WRITE and request.path in self.pending:
            read = self.pending[request.path]
            return self.respond({"reason": "not_reread", "reread": read})
        _, selected, params = self.selector.see(request)
        if not selected:
            return None
        read = request.path
        if self.reread is not None:
            read = PLACEHOLDER.sub(lambda m: params[m[1]], self.reread)
        self.pending[request.path] = read
        return self.respond({"reason": "fired", "reread": read})

    def observe(self, request, response, env):
        if request.method == "GET" and 200 <= response.status < 300:
            for write, read in list(self.pending.items()):
                if read == request.path:
                    del self.pending[write]


class LostAck(Fault):
    """The write is forwarded and commits; the agent receives 502 instead of the answer.

    It counts only forwarded matching writes the service accepted (2xx): occurrence 1 is
    the first write that actually committed.
    """

    kind = "lost_ack"
    statuses = range(500, 600)
    default_status = 502
    default_body = {"error": "bad_gateway"}
    methods = WRITE
    allowed = WRITE

    def after(self, request, response, env):
        if not 200 <= response.status < 300:
            return None
        _, selected, _ = self.selector.see(request)
        if selected:
            return self.respond({"reason": "fired", "upstream_status": response.status})
        return None


class Revoke(Fault):
    """403 on writes once the trigger (``match.after``) has been seen; reads still pass."""

    kind = "revoke"
    statuses = (401, 403)
    default_status = 403
    default_body = {"error": "forbidden", "detail": "write permission revoked"}
    methods = WRITE
    allowed = WRITE
    occurrence = "every"

    def before(self, request, env):
        _, selected, _ = self.selector.see(request)
        return self.respond({"reason": "fired"}) if selected else None


KINDS = {cls.kind: cls for cls in (RateLimit, Precondition, LostAck, Revoke)}


def build_faults(specs, render, seed):
    faults = []
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict) or "kind" not in spec:
            raise ScenarioError(f"faults[{index}]: each fault is a mapping with a kind")
        kind = spec["kind"]
        if kind in LATER:
            raise ScenarioError(
                f"faults[{index}]: {kind} is planned for milestone 3 and not implemented yet"
            )
        if kind not in KINDS:
            raise ScenarioError(f"faults[{index}]: unknown fault kind {kind!r}; known: {sorted(KINDS)}")
        faults.append(KINDS[kind](index, spec, render, seed))
    return faults
