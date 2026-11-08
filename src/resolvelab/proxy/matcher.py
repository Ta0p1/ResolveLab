"""Which requests a fault applies to: method, path template, body predicate and occurrence.

    match:
      method: POST                  # a method, a list, "write", "read" or "any" (the default)
      path: /orders/{order_id}/refund
      body: {amount: 30}            # optional: the JSON body contains these values
      occurrence: 1                 # the nth match, a list of them, or "every"
      after:                        # optional trigger: count only requests after it
        method: GET
        path: /orders/{order_id}

Scenario parameters (``{order_id}``) are substituted before matching; any other placeholder
(``{id}``) matches one path segment, so ``/orders/{id}/refund`` matches every order. Without
``path`` every path matches. The query string is not part of the match.
"""

import json
import re
from dataclasses import dataclass

WRITE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
READ = frozenset({"GET", "HEAD"})
METHODS = WRITE | READ | {"OPTIONS"}
SETS = {"write": WRITE, "read": READ, "any": None}
PLACEHOLDER = re.compile(r"\{(\w+)\}")


class ScenarioError(ValueError):
    """A scenario file that cannot be run as written."""


def parse_methods(value, where):
    if isinstance(value, str):
        if value.lower() in SETS:
            return SETS[value.lower()]
        value = [value]
    if not isinstance(value, list) or not value:
        raise ScenarioError(f"{where}: method must be a method, a list of methods, write, read or any")
    methods = frozenset(str(m).upper() for m in value)
    unknown = methods - METHODS
    if unknown:
        raise ScenarioError(f"{where}: unknown method(s) {sorted(unknown)}")
    return methods


def compile_template(template, where):
    """A path template as an anchored regex; each placeholder binds one segment."""
    if not isinstance(template, str) or not template.startswith("/"):
        raise ScenarioError(f"{where}: a path template must be a string starting with '/'")
    if "?" in template:
        raise ScenarioError(f"{where}: a path template does not include a query string")
    pattern, names, last = "", [], 0
    for m in PLACEHOLDER.finditer(template):
        if m[1] in names:
            raise ScenarioError(f"{where}: placeholder {{{m[1]}}} appears twice")
        names.append(m[1])
        pattern += re.escape(template[last : m.start()]) + f"(?P<{m[1]}>[^/]+)"
        last = m.end()
    return re.compile(pattern + re.escape(template[last:]) + r"\Z")


def lookup(value, dotted):
    """``a.b`` inside nested objects, as (found, value)."""
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value


def json_body(content):
    if not content:
        return None
    try:
        return json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return None


@dataclass(frozen=True)
class Matcher:
    """Method, path template and an optional body predicate."""

    template: str | None = None  # None matches every path
    methods: frozenset | None = None  # None matches every method
    body: dict | None = None

    def __post_init__(self):
        regex = None if self.template is None else compile_template(self.template, self.template)
        object.__setattr__(self, "_regex", regex)

    def match(self, request):
        """The bound placeholders when the request matches, else None."""
        if self.methods is not None and request.method not in self.methods:
            return None
        params = {}
        if self._regex is not None:
            found = self._regex.match(request.path)
            if found is None:
                return None
            params = found.groupdict()
        if self.body is not None:
            value = json_body(request.body)
            for key, expected in self.body.items():
                present, actual = lookup(value, key)
                if not present or actual != expected:
                    return None
        return params


class Selector:
    """A matcher plus an occurrence rule, with the counters that make it deterministic.

    It counts only the requests shown to it. The engine shows a request to a fault only when
    no earlier fault has answered it, so each fault's counts follow what it actually saw.
    """

    def __init__(self, matcher, nth=frozenset({1}), after=None):
        self.matcher, self.nth, self.after = matcher, nth, after  # nth None: every match
        self.count = 0  # matches seen while armed
        self.fired = False  # as a trigger: one of its selected requests has been seen

    def see(self, request):
        """(matched, selected, params) for this request, updating the counters.

        ``matched`` means the request fits the matcher and the trigger (if any) had already
        fired before it; the trigger's own request is never "after" it.
        """
        params = self.matcher.match(request)
        armed = self.after is None or self.after.fired
        matched, selected = params is not None and armed, False
        if matched:
            self.count += 1
            selected = self.nth is None or self.count in self.nth
        if self.after is not None and not self.after.fired:
            self.after.see(request)
        if selected:
            self.fired = True
        return matched, selected, params or {}


def parse_occurrence(value, where):
    if value == "every":
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        value = [value]
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(n, int) and not isinstance(n, bool) and n >= 1 for n in value)
    ):
        raise ScenarioError(f"{where}: occurrence must be a positive integer, a list of them or every")
    return frozenset(value)


def parse_selector(spec, where, render, *, methods=None, occurrence=1, allowed=None):
    """A selector from a scenario ``match`` mapping.

    ``methods`` is the default method set, ``allowed`` the set a fault accepts at all.
    """
    spec = {} if spec is None else spec
    if not isinstance(spec, dict):
        raise ScenarioError(f"{where}: match must be a mapping")
    unknown = set(spec) - {"method", "path", "body", "occurrence", "after"}
    if unknown:
        raise ScenarioError(f"{where}: unknown match key(s) {sorted(unknown)}")
    if "method" in spec:
        methods = parse_methods(spec["method"], where)
    if allowed is not None and (methods is None or not methods <= allowed):
        raise ScenarioError(f"{where}: this fault only applies to {sorted(allowed)}")
    body = spec.get("body")
    if body is not None and not isinstance(body, dict):
        raise ScenarioError(f"{where}: body must be a mapping of field to value")
    template = render(spec["path"], where, wildcards=True) if "path" in spec else None
    after = None
    if spec.get("after") is not None:
        after = parse_selector(spec["after"], f"{where}.after", render)
    nth = parse_occurrence(spec.get("occurrence", occurrence), where)
    return Selector(Matcher(template, methods, body), nth, after)
