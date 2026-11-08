"""Scenario files: the faults, the state probe and the grading rules for one task, in YAML.

    name: refund-lost-ack
    upstream: http://127.0.0.1:8080
    params: {order_id: "7", customer_id: c1}
    task: "Refund order {order_id} in full. Do not change other orders. Verify the refund."
    probe:
      - GET /orders/{order_id}
      - GET /orders?customer={customer_id}
    faults:
      - kind: lost_ack
        match: {method: POST, path: "/orders/{order_id}/refund", occurrence: 1}
    grade:
      allowed_changes: ["/orders/{order_id}"]
      expected_state: {"/orders/{order_id}": {refund_status: refunded}}
      exactly_once: {method: POST, path: "/orders/{order_id}/refund", key_header: Idempotency-Key}

YAML needs quotes around a path with braces inside a flow mapping or list (``{...}``,
``[...]``); in block style it does not. A ``.json`` file with the same keys works too.
Unknown keys are refused, and so are the rules planned for later milestones, so a typo or an
unimplemented rule never makes a verdict look stricter than it is.

The proxy refuses an upstream that is not a loopback address unless the scenario lists its
host in ``allow_hosts``: pointing it at another machine takes a second, explicit line.
"""

import copy
import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .faults import build_faults
from .matcher import PLACEHOLDER, Matcher, ScenarioError, compile_template, parse_methods

KEYS = {
    "name",
    "upstream",
    "allow_hosts",
    "params",
    "task",
    "api",
    "probe",
    "probe_headers",
    "faults",
    "grade",
    "max_steps",
    "redact_headers",
    "control_prefix",
    "timeout",
}
GRADE_KEYS = {"outcome", "allowed_changes", "expected_state", "exactly_once"}
LATER_RULES = {"fresh_verification", "honest_claim", "justified_escalation"}
OUTCOMES = ("resolved", "escalated")
REDACT = frozenset({"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"})
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class UpstreamRefused(ScenarioError):
    """The upstream is not loopback and the scenario does not name its host."""


def is_loopback(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_upstream(url, allow_hosts=()):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ScenarioError(f"upstream must be an http(s) URL with a host, got {url!r}")
    if parts.query or parts.fragment:
        raise ScenarioError("upstream must not have a query or fragment")
    host = parts.hostname
    if not is_loopback(host) and host.lower() not in {h.lower() for h in allow_hosts}:
        raise UpstreamRefused(
            f"Refusing upstream {url}: {host} is not a loopback address. The proxy is for test "
            f"environments; list the host under allow_hosts in the scenario to use it."
        )
    return url.rstrip("/")


@dataclass(frozen=True)
class ProbeSpec:
    """One GET of the state probe. A list response is split into items by ``key``."""

    path: str  # concrete, may carry a query
    items: str | None = None  # field holding the list; None: the body itself, if it is one
    key: str = "id"
    resource: str | None = None  # an item's resource path, e.g. /orders/{id}

    @property
    def base(self):
        return self.path.partition("?")[0]

    def item_path(self, item):
        template = self.resource or f"{self.base.rstrip('/')}/{{{self.key}}}"
        return PLACEHOLDER.sub(lambda m: str(item[m[1]]), template)


@dataclass(frozen=True)
class WriteClass:
    """A class of writes for ``exactly_once``: method, path template and the key header."""

    method: frozenset
    template: str
    key_header: str

    @property
    def matcher(self):
        return Matcher(self.template, self.method)


@dataclass(frozen=True)
class Grade:
    outcome: str = "resolved"
    allowed_changes: dict | None = None  # resource template -> frozenset of fields, or None: all
    expected_state: dict | None = None  # resource path -> {field: value}
    exactly_once: tuple | None = None  # WriteClass, ...


def mapping(value, where):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ScenarioError(f"{where} must be a mapping")
    return value


class Scenario:
    """A validated scenario. ``data`` is the effective scenario, written to every log header."""

    def __init__(self, data):
        if not isinstance(data, dict):
            raise ScenarioError("A scenario is a mapping")
        unknown = set(data) - KEYS
        if unknown:
            raise ScenarioError(f"Unknown scenario key(s) {sorted(unknown)}")
        self.data = copy.deepcopy(data)
        name = data.get("name")
        if not isinstance(name, str) or not NAME.match(name):
            raise ScenarioError("name is required: letters, digits, '.', '_' or '-'")
        self.name = name
        self.params = {str(k): str(v) for k, v in mapping(data.get("params"), "params").items()}
        self.data["params"] = dict(self.params)
        self.allow_hosts = tuple(data.get("allow_hosts") or ())
        if not all(isinstance(h, str) and h for h in self.allow_hosts):
            raise ScenarioError("allow_hosts is a list of host names")
        if "upstream" not in data:
            raise ScenarioError("upstream is required")
        self.upstream = check_upstream(str(data["upstream"]), self.allow_hosts)
        if not isinstance(data.get("task"), str) or not data["task"].strip():
            raise ScenarioError("task is required")
        self.task = self.render(data["task"], "task")
        self.api = data.get("api")
        if self.api is not None and not isinstance(self.api, str):
            raise ScenarioError("api is free text describing the endpoints")
        self.max_steps = data.get("max_steps", 24)
        if not isinstance(self.max_steps, int) or isinstance(self.max_steps, bool) or self.max_steps < 1:
            raise ScenarioError("max_steps must be a positive integer")
        self.timeout = data.get("timeout", 30)
        if not isinstance(self.timeout, (int, float)) or not 0 < self.timeout <= 600:
            raise ScenarioError("timeout is the upstream timeout in seconds (up to 600)")
        redact = data.get("redact_headers", [])
        if not isinstance(redact, list):
            raise ScenarioError("redact_headers is a list of header names")
        self.redact = REDACT | {str(h).lower() for h in redact}
        self.control_prefix = data.get("control_prefix", "/_resolvelab")
        if (
            not isinstance(self.control_prefix, str)
            or not self.control_prefix.startswith("/")
            or self.control_prefix.endswith("/")
        ):
            raise ScenarioError("control_prefix is a path such as /_resolvelab")
        self.probe = self._probe(data.get("probe") or [])
        self.probe_headers = {
            str(k): str(v) for k, v in mapping(data.get("probe_headers"), "probe_headers").items()
        }
        self.fault_specs = data.get("faults") or []
        if not isinstance(self.fault_specs, list):
            raise ScenarioError("faults is a list")
        self.faults(0)  # validate once; every episode builds fresh fault state
        self.grade = self._grade(mapping(data.get("grade"), "grade"))

    # -- templates ----------------------------------------------------------------------

    def render(self, template, where, wildcards=False):
        """Substitute scenario parameters. Other placeholders stay (as wildcards) or fail."""
        if not isinstance(template, str):
            raise ScenarioError(f"{where}: expected a string, got {template!r}")

        def substitute(m):
            if m[1] in self.params:
                return self.params[m[1]]
            if wildcards:
                return m[0]
            raise ScenarioError(f"{where}: unknown parameter {{{m[1]}}}")

        return PLACEHOLDER.sub(substitute, template)

    def faults(self, seed):
        return build_faults(self.fault_specs, self.render, seed)

    # -- probe and grade ----------------------------------------------------------------

    def _probe(self, entries):
        if not isinstance(entries, list):
            raise ScenarioError("probe is a list of GET requests")
        specs = []
        for i, entry in enumerate(entries):
            where = f"probe[{i}]"
            if isinstance(entry, str):
                method, _, path = entry.strip().partition(" ")
                if not path:
                    method, path = "GET", method
                if method.upper() != "GET":
                    raise ScenarioError(f"{where}: the probe only sends GET requests")
                specs.append(ProbeSpec(self.render(path.strip(), where)))
            elif isinstance(entry, dict):
                unknown = set(entry) - {"get", "items", "key", "resource"}
                if unknown or "get" not in entry:
                    raise ScenarioError(f"{where}: a probe mapping takes get, items, key, resource")
                resource = entry.get("resource")
                if resource is not None:
                    resource = self.render(resource, f"{where}.resource", wildcards=True)
                    compile_template(resource, f"{where}.resource")
                specs.append(
                    ProbeSpec(
                        self.render(entry["get"], where),
                        entry.get("items"),
                        str(entry.get("key", "id")),
                        resource,
                    )
                )
            else:
                raise ScenarioError(f"{where}: expected 'GET /path' or a mapping")
            if not specs[-1].path.startswith("/"):
                raise ScenarioError(f"{where}: a probe path starts with '/'")
        return tuple(specs)

    def _grade(self, spec):
        later = set(spec) & LATER_RULES
        if later:
            raise ScenarioError(
                f"grade: {sorted(later)} planned for milestone 3 and not implemented yet; "
                f"milestone 1 grades {sorted(GRADE_KEYS - {'outcome'})}"
            )
        unknown = set(spec) - GRADE_KEYS
        if unknown:
            raise ScenarioError(f"grade: unknown rule(s) {sorted(unknown)}")
        outcome = spec.get("outcome", "resolved")
        if outcome not in OUTCOMES:
            raise ScenarioError(f"grade.outcome must be one of {OUTCOMES}")
        allowed = None
        if "allowed_changes" in spec:
            allowed = {}
            value = spec["allowed_changes"] or []
            if not isinstance(value, (dict, list)):
                raise ScenarioError("grade.allowed_changes is a list of resources or a mapping")
            items = value.items() if isinstance(value, dict) else [(p, None) for p in value]
            for path, fields in items:
                where = f"grade.allowed_changes[{path!r}]"
                template = self.render(path, where, wildcards=True)
                if "?" not in template:
                    compile_template(template, where)
                if fields in (None, "*"):
                    allowed[template] = None
                elif isinstance(fields, list) and all(isinstance(f, str) for f in fields):
                    allowed[template] = frozenset(fields)
                else:
                    raise ScenarioError(f"{where}: fields are a list of names or '*'")
        expected = None
        if "expected_state" in spec:
            expected = {}
            for path, fields in mapping(spec["expected_state"], "grade.expected_state").items():
                where = f"grade.expected_state[{path!r}]"
                resource = self.render(path, where)
                if not isinstance(fields, dict) or not fields:
                    raise ScenarioError(f"{where}: expected fields are a non-empty mapping")
                if not any(self._probes(resource, p) for p in self.probe):
                    raise ScenarioError(f"{where}: no probe entry reads {resource}")
                expected[resource] = dict(fields)
        once = None
        if "exactly_once" in spec:
            value = spec["exactly_once"]
            value = [value] if isinstance(value, dict) else value
            if not isinstance(value, list) or not value:
                raise ScenarioError("grade.exactly_once is a write class or a list of them")
            once = []
            for i, entry in enumerate(value):
                where = f"grade.exactly_once[{i}]"
                if not isinstance(entry, dict) or set(entry) - {"method", "path", "key_header"}:
                    raise ScenarioError(f"{where}: takes method, path and key_header")
                if "method" not in entry or "path" not in entry:
                    raise ScenarioError(f"{where}: method and path are required")
                key = str(entry.get("key_header", "Idempotency-Key"))
                if key.lower() in self.redact:
                    raise ScenarioError(f"{where}: key_header {key} is redacted from the log")
                template = self.render(entry["path"], where, wildcards=True)
                compile_template(template, where)
                once.append(WriteClass(parse_methods(entry["method"], where), template, key))
            once = tuple(once)
        return Grade(outcome, allowed, expected, once)

    @staticmethod
    def _probes(resource, spec):
        if spec.path == resource:
            return True
        template = spec.resource or f"{spec.base.rstrip('/')}/{{{spec.key}}}"
        return bool(compile_template(template, template).match(resource))

    # -- identity -----------------------------------------------------------------------

    @property
    def sha256(self):
        text = json.dumps(self.data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def with_overrides(self, params=None, upstream=None):
        return Scenario(overridden(self.data, params, upstream))


def overridden(data, params=None, upstream=None):
    data = copy.deepcopy(data)
    if params and isinstance(data, dict):
        data["params"] = {**(data.get("params") or {}), **params}
    if upstream and isinstance(data, dict):
        data["upstream"] = upstream
    return data


def load_scenario(path, *, params=None, upstream=None):
    """A scenario from a ``.yaml``/``.yml`` or ``.json`` file, with optional overrides."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        import yaml

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ScenarioError(f"{path}: not valid YAML: {exc}") from exc
    return Scenario(overridden(data, params, upstream))
