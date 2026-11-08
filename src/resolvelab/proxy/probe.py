"""The state probe: read-only GETs straight to the service, before and after an episode.

The probe never goes through the proxy, so faults cannot touch it and the agent never sees
it. Each entry's response is logged as it arrived. For grading, a response is split into
resources: a JSON list of objects that all carry the key field (``id`` by default) becomes
one resource per item (``/orders?customer=c1`` -> ``/orders/7``, ``/orders/8``), so a change
to one order is not a change to "the list". A mapping entry names the list field and the
item path when the service wraps its lists:

    probe:
      - GET /orders/{order_id}
      - {get: "/orders?customer={customer_id}", items: orders, key: id, resource: "/orders/{id}"}

What the probe does not read, the grader cannot see.
"""

import os

import httpx

from .log import encode_body
from .matcher import compile_template, lookup

MISSING = object()


def probe_headers(scenario):
    """Probe credentials come from the environment variables the scenario names."""
    headers = {}
    for name, variable in scenario.probe_headers.items():
        value = os.environ.get(variable)
        if value is None:
            raise RuntimeError(f"probe_headers: environment variable {variable} is not set")
        headers[name] = value
    return headers


def take(scenario, client):
    """One record per probe entry, in scenario order."""
    headers = probe_headers(scenario)
    records = []
    for spec in scenario.probe:
        try:
            response = client.get(spec.path, headers=headers)
        except httpx.HTTPError as exc:
            records.append({"get": spec.path, "error": f"{type(exc).__name__}: {exc}"})
            continue
        records.append(
            {"get": spec.path, "status": response.status_code, **encode_body(response.content)}
        )
    return records


def body_of(record):
    if "json" in record:
        return record["json"]
    return record.get("text", record.get("base64"))


def resources(spec, record):
    """resource path -> {"status", "body"} for one probe response."""
    if "error" in record:
        return {spec.path: {"status": None, "error": record["error"]}}
    status, body = record["status"], body_of(record)
    entries = None
    if 200 <= status < 300:
        if spec.items is not None and isinstance(body, dict):
            entries = body.get(spec.items)
        elif spec.items is None and isinstance(body, list):
            entries = body
    keyed = isinstance(entries, list) and all(
        isinstance(item, dict) and spec.key in item for item in entries
    )
    if not keyed:
        return {spec.path: {"status": status, "body": body}}
    out = {}
    if isinstance(body, dict):
        # The list's own fields (a total, a cursor) stay a resource of their own.
        out[spec.path] = {"status": status, "body": {k: v for k, v in body.items() if k != spec.items}}
    for item in entries:
        out[spec.item_path(item)] = {"status": status, "body": item}
    return out


def changes(specs, before, after):
    """Every resource or field that differs between two snapshots, each once."""
    if len(before) != len(specs) or len(after) != len(specs):
        raise ValueError("The snapshots do not match the scenario's probe entries")
    found = {}
    for spec, b_record, a_record in zip(specs, before, after):
        b, a = resources(spec, b_record), resources(spec, a_record)
        for path in sorted(set(b) | set(a)):
            old, new = b.get(path), a.get(path)
            if old == new:
                continue
            if old is None or new is None or old.get("status") != new.get("status"):
                found.setdefault((path, None), (old, new))
                continue
            ob, nb = old.get("body"), new.get("body")
            if isinstance(ob, dict) and isinstance(nb, dict):
                for field in sorted(set(ob) | set(nb)):
                    if ob.get(field, MISSING) != nb.get(field, MISSING):
                        found.setdefault((path, field), (ob.get(field), nb.get(field)))
            else:
                found.setdefault((path, None), (old, new))
    return [
        {"resource": path, "field": field, "before": old, "after": new}
        for (path, field), (old, new) in sorted(found.items(), key=lambda kv: (kv[0][0], kv[0][1] or ""))
    ]


def find(specs, records, path):
    """The first probed state of a resource, or None."""
    for spec, record in zip(specs, records):
        entry = resources(spec, record).get(path)
        if entry is not None:
            return entry
    return None


def covers(template, resource):
    """Whether an allowed-change template names this resource."""
    if "?" in template or "?" in resource:
        return template == resource
    return bool(compile_template(template, template).match(resource))


def field_value(body, field):
    return lookup(body, field)
