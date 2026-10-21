"""Typed agent tools translated into HTTP requests without hidden recovery."""

from urllib.parse import quote

import httpx

from .schema import validate_action


class DeskAdapter:
    def __init__(self, base_url):
        self.client = httpx.Client(base_url=base_url, timeout=5, trust_env=False)
        self.requests = []

    def close(self):
        self.client.close()

    def dispatch(self, decision):
        validate_action(decision.model_dump())
        name, args = decision.name, decision.arguments
        if name == "finish":
            return {"finished": args["outcome"]}
        kwargs = {}
        if name == "list_tickets":
            method, path, kwargs = "GET", "/tickets", {"params": args}
        elif name == "get_ticket":
            method, path = "GET", "/tickets/" + quote(args["ticket_id"], safe="")
        elif name == "patch_ticket":
            method, path = "PATCH", "/tickets/" + quote(args["ticket_id"], safe="")
            kwargs = {
                "headers": {"If-Match": args["etag"], "Idempotency-Key": args["idempotency_key"]},
                "json": {"priority": args["priority"], "status": args["status"]},
            }
        elif name == "wait":
            method, path, kwargs = "POST", "/clock", {"json": args}
        else:
            method, path, kwargs = "POST", "/escalations", {"json": args}
        record = {"method": method, "path": path, "request": kwargs}
        try:
            response = self.client.request(method, path, **kwargs)
            result = {"status": response.status_code, "body": response.json()}
            for header, key in (("etag", "etag"), ("retry-after", "retry_after")):
                if header in response.headers:
                    result[key] = response.headers[header]
        except (httpx.HTTPError, ValueError) as exc:
            result = {"status": 0, "error": type(exc).__name__, "commit_state": "unknown"}
        record["response"] = result
        self.requests.append(record)
        return result
