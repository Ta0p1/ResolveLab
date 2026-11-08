"""Concurrent PATCHes against two workers on one store, released at the same instant.

Used by the tests and ``resolvelab durable race``. With ``hold_ms`` the worker that wins the
write lock holds it while committing, so the other request is certain to arrive while the
first transaction is open, rather than only by luck of timing.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import httpx

from ..casedesk.world import WorldState
from .desk import DurableDesk

# A fault-free two-worker episode spec for races outside the agent loop.
RACE_SPEC = {
    "id": "durable-race-direct",
    "pool": "durable",
    "composition": "race_direct",
    "faults": [],
    "workers": 2,
    "n_records": 3,
    "target_pos": 1,
    "phrasing": "f0",
    "injection": None,
    "record_seed": 424242424,
}


def read_ticket(desk, worker, ticket_id):
    with httpx.Client(base_url=desk.url(worker), timeout=30, trust_env=False) as client:
        response = client.get("/tickets/" + quote(ticket_id, safe=""))
    return response.headers["etag"], response.json()


def concurrent_patches(desk, ticket_id, sends):
    """``sends``: ``(worker, idempotency_key, etag, body)`` each; all leave on one barrier."""
    clients = [httpx.Client(base_url=desk.url(w), timeout=30, trust_env=False) for w, *_ in sends]
    barrier = threading.Barrier(len(sends))

    def send(index):
        worker, key, etag, body = sends[index]
        barrier.wait()
        response = clients[index].patch(
            "/tickets/" + quote(ticket_id, safe=""),
            headers={"If-Match": etag, "Idempotency-Key": key},
            json=body,
        )
        return {"worker": worker, "key": key, "status": response.status_code, "body": response.json()}

    try:
        with ThreadPoolExecutor(len(sends)) as pool:
            return list(pool.map(send, range(len(sends))))
    finally:
        for client in clients:
            client.close()


def race(case, *, store="durable", hold_ms=200, per_worker=2):
    """Run one race case and return (responses, snapshot). Cases:

    ``same_key``: identical requests, one key: one commit, every response the saved 200.
    ``new_keys``: identical bodies and ETag, a key each: one commit, the rest 412.
    ``key_reuse``: one key, different bodies: one commit, a different body gets 409.
    """
    world = WorldState(RACE_SPEC)
    target, desired = world.target, world.desired
    other = {
        "priority": next(p for p in ("low", "normal", "high", "urgent") if p != desired["priority"]),
        "status": desired["status"],
    }
    with DurableDesk(RACE_SPEC, store=store, hold_ms=hold_ms) as desk:
        etag, _ = read_ticket(desk, 0, target)
        sends = []
        for i in range(2 * per_worker):
            worker = i % 2
            if case == "same_key":
                sends.append((worker, "race-1", etag, desired))
            elif case == "new_keys":
                sends.append((worker, f"race-{i}", etag, desired))
            elif case == "key_reuse":
                sends.append((worker, "race-1", etag, desired if i % 2 == 0 else other))
            else:
                raise ValueError(f"Unknown race case {case!r}")
        responses = concurrent_patches(desk, target, sends)
    return responses, desk.snapshot
