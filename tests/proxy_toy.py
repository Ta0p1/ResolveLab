"""A toy order service for the fault-proxy tests: not CaseDesk, and no faults of its own.

- ``GET /orders/{id}`` returns the order with an ``ETag``; ``GET /orders?customer=c1`` a bare
  JSON list.
- ``POST /orders/{id}/refund`` with ``{"amount": n}`` adds a refund. A repeated
  ``Idempotency-Key`` gets the saved answer and refunds nothing; a new key refunds again (the
  service does not cap refunds, so a duplicate shows in its state).
- ``PATCH /orders/{id}`` changes ``address`` or ``status`` and needs ``If-Match``.

The service also remembers the last ``Authorization`` header it received, so tests can check
that credentials reach it while the log redacts them.
"""

import copy
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ORDERS = {
    "7": {
        "id": "7",
        "customer": "c1",
        "amount": 30,
        "refunded": 0,
        "status": "open",
        "address": "1 Old Road",
    },
    "8": {
        "id": "8",
        "customer": "c1",
        "amount": 12,
        "refunded": 0,
        "status": "open",
        "address": "2 Side Street",
    },
    "9": {
        "id": "9",
        "customer": "c2",
        "amount": 50,
        "refunded": 0,
        "status": "open",
        "address": "3 High Street",
    },
}


class Shop:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.orders = copy.deepcopy(ORDERS)
        for order in self.orders.values():
            order["version"] = 1
            order["refund_status"] = "none"
        self.receipts, self.refunds, self.last_authorization = {}, [], None


def etag(order):
    return f'"v{order["version"]}"'


def create_app(shop):
    app = FastAPI()

    @app.middleware("http")
    async def remember_authorization(request, call_next):
        if "authorization" in request.headers:
            shop.last_authorization = request.headers["authorization"]
        return await call_next(request)

    @app.get("/orders")
    def list_orders(customer: str | None = None):
        with shop.lock:
            return [o for _, o in sorted(shop.orders.items()) if customer in (None, o["customer"])]

    @app.get("/orders/{order_id}")
    def get_order(order_id: str):
        with shop.lock:
            order = shop.orders.get(order_id)
            if order is None:
                return JSONResponse({"error": "not_found"}, 404)
            return JSONResponse(order, headers={"ETag": etag(order)})

    @app.post("/orders/{order_id}/refund")
    async def refund(order_id: str, request: Request):
        body = await request.json()
        key = request.headers.get("idempotency-key")
        with shop.lock:
            if key is not None and key in shop.receipts:
                return JSONResponse(shop.receipts[key], 201)
            order = shop.orders.get(order_id)
            if order is None:
                return JSONResponse({"error": "not_found"}, 404)
            amount = body.get("amount")
            if not isinstance(amount, int) or amount <= 0:
                return JSONResponse({"error": "invalid_amount"}, 422)
            order["refunded"] += amount
            order["refund_status"] = "refunded" if order["refunded"] >= order["amount"] else "partial"
            order["version"] += 1
            receipt = {"refund_id": f"R-{len(shop.refunds) + 1}", "order": copy.deepcopy(order)}
            shop.refunds.append({"order": order_id, "amount": amount, "key": key})
            if key is not None:
                shop.receipts[key] = receipt
            return JSONResponse(receipt, 201)

    @app.patch("/orders/{order_id}")
    async def patch_order(order_id: str, request: Request):
        body = await request.json()
        with shop.lock:
            order = shop.orders.get(order_id)
            if order is None:
                return JSONResponse({"error": "not_found"}, 404)
            match = request.headers.get("if-match")
            if match is None:
                return JSONResponse({"error": "if_match_required"}, 428)
            if match != etag(order):
                return JSONResponse({"error": "precondition_failed"}, 412)
            if not body or set(body) - {"address", "status"}:
                return JSONResponse({"error": "only address and status can change"}, 422)
            order.update(body)
            order["version"] += 1
            return JSONResponse(order, headers={"ETag": etag(order)})

    return app


class ShopServer:
    """The toy service on a real loopback socket."""

    def __init__(self):
        self.shop = Shop()

    def __enter__(self):
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(128)
        self.url = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        config = uvicorn.Config(
            create_app(self.shop), log_level="error", access_log=False, lifespan="off"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True
        )
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("The toy service failed to start")
            time.sleep(0.005)
        return self

    def __exit__(self, *_):
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.socket.close()
