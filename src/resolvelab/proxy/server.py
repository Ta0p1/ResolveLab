"""The proxy over real HTTP: a small ASGI app around ``Proxy.handle``, served by uvicorn."""

import socket
import threading
import time

import uvicorn
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

from .log import Request, lower_headers


class ProxyApp:
    """Every path and method goes to the engine; the engine serialises requests itself."""

    def __init__(self, proxy):
        self.proxy = proxy

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return
        incoming = StarletteRequest(scope, receive)
        raw = scope.get("raw_path") or scope["path"].encode()
        request = Request(
            method=scope["method"].upper(),
            path=raw.decode("latin-1").partition("?")[0],
            query=scope.get("query_string", b"").decode("latin-1"),
            headers=lower_headers(
                (k.decode("latin-1"), v.decode("latin-1")) for k, v in scope["headers"]
            ),
            body=await incoming.body(),
        )
        response = await run_in_threadpool(self.proxy.handle, request)
        reply = StarletteResponse(response.body, status_code=response.status, headers=response.headers)
        await reply(scope, receive, send)


class ProxyServer:
    """Serves one episode's proxy on a bound socket (loopback by default, port 0: any free)."""

    def __init__(self, proxy, host="127.0.0.1", port=0):
        self.proxy, self.host, self.port = proxy, host, port

    def __enter__(self):
        family = socket.AF_INET6 if ":" in self.host else socket.AF_INET
        self.socket = socket.socket(family)
        self.socket.bind((self.host, self.port))
        self.socket.listen(128)
        port = self.socket.getsockname()[1]
        host = f"[{self.host}]" if family == socket.AF_INET6 else self.host
        self.url = f"http://{host}:{port}"
        config = uvicorn.Config(
            ProxyApp(self.proxy), log_level="error", access_log=False, lifespan="off"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True
        )
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                self.__exit__(None, None, None)
                raise RuntimeError("The proxy failed to start")
            time.sleep(0.005)
        return self

    def __exit__(self, *_):
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.socket.close()
        if self.thread.is_alive():
            raise RuntimeError("The proxy failed to stop")
