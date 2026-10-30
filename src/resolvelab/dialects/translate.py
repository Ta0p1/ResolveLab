"""Translate between a dialect and the canonical CaseDesk contract, one episode at a time.

The model only ever sees the dialect. Its action is validated against the dialect's schema,
mapped to the canonical action, executed by the unchanged CaseDesk service, and the canonical
result is mapped back. The grader, the teacher and the diagnostics keep working on canonical
state, so a dialect changes what the agent must read and write, never what counts as success.

A concurrency token the model mangles is passed through as written; the service then rejects
it as stale, exactly as a mis-copied ETag is rejected in the canonical contract.
"""

import json
import math
import random
import re

from .spec import TOOLS

TOKEN_PATTERNS = {"weak_etag": re.compile(r'^W/"(\d+)"$'), "version_tag": re.compile(r"^rev-(\d+)$")}
ETAG = re.compile(r'^"v(\d+)"$')
MAX_PAGE = 20


def _title(name):
    return name.replace("_", " ").title()


def _model_title(name):
    return "".join(part.title() for part in name.split("_"))


class Translator:
    def __init__(self, dialect, seed=0):
        self.d = dialect
        self.tool_of = {v: k for k, v in dialect.tools.items()}
        rng = random.Random(f"{dialect.name}:{seed}")
        self.page_token = {o: f"pg_{rng.getrandbits(40):010x}" for o in range(2, 2 * MAX_PAGE, 2)}
        self.page_of_token = {v: k for k, v in self.page_token.items()}

    # -- schema ---------------------------------------------------------------------------

    def arguments(self):
        """canonical tool -> [(canonical arg, dialect arg, JSON schema)] in canonical order."""
        d = self.d
        cursor = {"type": "string"}
        if d.cursor in ("page", "opaque"):
            cursor["description"] = (
                f"Empty string for first page; otherwise {d.fields['next_cursor']} from response"
            )
        elif d.cursor == "offset":
            cursor = {
                "description": f"0 for the first page; otherwise {d.fields['next_cursor']} from response",
                "minimum": 0,
                "type": "integer",
            }
        else:
            cursor = {
                "description": f"1 for the first page; otherwise {d.fields['next_cursor']} from response",
                "minimum": 1,
                "type": "integer",
            }
        token = {
            "description": f"Exact {self.token_word()} from latest successful {d.tools['get_ticket']}",
            "type": "integer" if d.token == "revision" else "string",
        }
        if d.unit == "seconds":
            wait = {"maximum": 60, "minimum": 1, "type": "integer"}
        else:
            wait = {"maximum": 60000, "minimum": 1000, "type": "integer"}
        key = {"description": "Unique operation key; reuse only for identical retry", "type": "string"}
        return {
            "list_tickets": [("cursor", d.args["cursor"], cursor)],
            "get_ticket": [("ticket_id", d.args["ticket_id"], {"type": "string"})],
            "patch_ticket": [
                ("ticket_id", d.args["ticket_id"], {"type": "string"}),
                ("etag", d.args["etag"], token),
                (
                    "priority",
                    d.args["priority"],
                    {"enum": list(d.priorities.values()), "type": "string"},
                ),
                ("status", d.args["status"], {"enum": list(d.statuses.values()), "type": "string"}),
                ("idempotency_key", d.args["idempotency_key"], key),
            ],
            "wait": [("seconds", d.args["seconds"], wait)],
            "escalate": [("reason", d.args["reason"], {"type": "string"})],
            "finish": [
                ("outcome", d.args["outcome"], {"enum": list(d.outcomes.values()), "type": "string"})
            ],
        }

    def parameters(self, canonical_tool):
        """The tool's argument schema in the same JSON shape Pydantic gives the study."""
        properties = {}
        for _, name, schema in self.arguments()[canonical_tool]:
            ordered = {
                k: schema[k] for k in ("description", "enum", "maximum", "minimum") if k in schema
            }
            properties[name] = {**ordered, "title": _title(name), "type": schema["type"]}
        return {
            "additionalProperties": False,
            "properties": properties,
            "required": list(properties),
            "title": _model_title(self.d.tools[canonical_tool]),
            "type": "object",
        }

    def schema(self):
        """Root ``anyOf`` of the six tools, like ``httpdesk.schema.action_schema``."""
        return {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": [self.d.tools[tool]]},
                        "arguments": self.parameters(tool),
                    },
                    "required": ["name", "arguments"],
                    "additionalProperties": False,
                }
                for tool in TOOLS
            ]
        }

    def token_word(self):
        return {
            "etag": "ETag",
            "revision": "revision",
            "weak_etag": "weak ETag",
            "version_tag": "version tag",
        }[self.d.token]

    # -- dialect -> canonical ---------------------------------------------------------------

    def validate(self, action):
        """Check a dialect action exactly; return (canonical tool, dialect arguments)."""
        if not isinstance(action, dict) or set(action) != {"name", "arguments"}:
            raise ValueError("An action is an object with exactly name and arguments")
        tool = self.tool_of.get(action["name"]) if isinstance(action["name"], str) else None
        if tool is None:
            raise ValueError(f"Unknown tool {action['name']!r}")
        args = action["arguments"]
        spec = self.arguments()[tool]
        if not isinstance(args, dict) or set(args) != {name for _, name, _ in spec}:
            raise ValueError(f"{action['name']} takes exactly {[n for _, n, _ in spec]}")
        for _, name, schema in spec:
            value = args[name]
            kind = int if schema["type"] == "integer" else str
            if type(value) is not kind:
                raise ValueError(f"{name} must be {schema['type']}")
            if "enum" in schema and value not in schema["enum"]:
                raise ValueError(f"{name} must be one of {schema['enum']}")
            if kind is int and not schema.get("minimum", value) <= value <= schema.get("maximum", value):
                raise ValueError(f"{name} out of range")
        return tool, args

    def to_canonical(self, action):
        tool, args = self.validate(action)
        named = {canonical: args[name] for canonical, name, _ in self.arguments()[tool]}
        d = self.d
        if tool == "list_tickets":
            named["cursor"] = self._cursor_in(named["cursor"])
        elif tool == "patch_ticket":
            named["etag"] = self._token_in(named["etag"])
            named["priority"] = _invert(d.priorities)[named["priority"]]
            named["status"] = _invert(d.statuses)[named["status"]]
        elif tool == "wait" and d.unit == "milliseconds":
            named["seconds"] = min(60, max(1, math.ceil(named["seconds"] / 1000)))
        elif tool == "finish":
            named["outcome"] = _invert(d.outcomes)[named["outcome"]]
        return {"name": tool, "arguments": named}

    def _cursor_in(self, value):
        style = self.d.cursor
        if style == "page":
            return value
        if style == "opaque":
            if value == "":
                return ""
            page = self.page_of_token.get(value)
            return f"page-{page}" if page else f"unknown:{value}"
        first = 0 if style == "offset" else 1
        if value == first:
            return ""
        offset = value if style == "offset" else 2 * (value - 1)
        return f"page-{offset}"

    def _token_in(self, value):
        style = self.d.token
        if style == "etag":
            return value
        if style == "revision":
            return f'"v{value}"'
        match = TOKEN_PATTERNS[style].match(value)
        return f'"v{match.group(1)}"' if match else value

    # -- canonical -> dialect ---------------------------------------------------------------

    def from_canonical(self, action):
        """The dialect form of a canonical action (for the teacher and the demonstration)."""
        tool, named = action["name"], dict(action["arguments"])
        d = self.d
        if tool == "list_tickets":
            named["cursor"] = self._cursor_out(named["cursor"], first=True)
        elif tool == "patch_ticket":
            named["etag"] = self._token_out(named["etag"])
            named["priority"] = d.priorities[named["priority"]]
            named["status"] = d.statuses[named["status"]]
        elif tool == "wait" and d.unit == "milliseconds":
            named["seconds"] = 1000 * named["seconds"]
        elif tool == "finish":
            named["outcome"] = d.outcomes[named["outcome"]]
        args = {name: named[canonical] for canonical, name, _ in self.arguments()[tool]}
        return {"name": d.tools[tool], "arguments": args}

    def _cursor_out(self, value, first=False):
        style = self.d.cursor
        if style == "page":
            return value
        if value == "":
            if style == "opaque":
                return ""
            if first:
                return 0 if style == "offset" else 1
            return None  # no further page
        offset = int(value.removeprefix("page-"))
        if style == "opaque":
            return self.page_token[offset]
        return offset if style == "offset" else offset // 2 + 1

    def _token_out(self, value):
        style = self.d.token
        match = ETAG.match(value)
        if style == "etag" or not match:
            return value
        version = int(match.group(1))
        return {"revision": version, "weak_etag": f'W/"{version}"', "version_tag": f"rev-{version}"}[
            style
        ]

    def observe(self, tool, result):
        """The dialect form of a canonical tool result."""
        d, f = self.d, self.d.fields
        if tool == "finish":
            return {f["finished"]: d.outcomes[result["finished"]]}
        out = {"status": d.codes.get(result["status"], result["status"])}
        if result["status"] == 0:
            return out | {f["error"]: result.get("error"), f["commit_state"]: result.get("commit_state")}
        body = result.get("body", {})
        if "error" in body:
            mapped = {f["error"]: d.errors.get(body["error"], body["error"])}
            if "commit_state" in body:
                mapped[f["commit_state"]] = body["commit_state"]
            out["body"] = mapped
        elif tool == "list_tickets":
            out["body"] = {
                f["tickets"]: [
                    {f["id"]: t["id"], f["external_ref"]: t["external_ref"]} for t in body["tickets"]
                ],
                f["next_cursor"]: self._cursor_out(body["next_cursor"]),
            }
        elif tool == "get_ticket":
            mapped = {}
            for key, value in body.items():
                if key == "priority":
                    value = d.priorities[value]
                elif key == "status":
                    value = d.statuses[value]
                mapped[f[key]] = value
            token = self._token_out(result["etag"])
            if d.token in ("etag", "weak_etag"):
                out[f["etag"]] = token
            else:
                mapped[f["etag"]] = token
            out["body"] = mapped
        elif tool == "patch_ticket":
            out["body"] = {f["updated"]: body["updated"]}
        elif tool == "wait":
            amount = body["waited_seconds"] * (1000 if d.unit == "milliseconds" else 1)
            out["body"] = {f["waited_seconds"]: amount}
        elif tool == "escalate":
            out["body"] = {f["ticket"]: body["ticket"]}
        if "retry_after" in result:
            seconds = int(result["retry_after"])
            if d.unit == "milliseconds":
                out[f["retry_after"]] = 1000 * seconds
            else:
                out[f["retry_after"]] = result["retry_after"]
        return out

    def action_text(self, action):
        """Serialise a dialect action like ``httpdesk.schema.action_json`` does."""
        tool = self.tool_of[action["name"]]
        args = {name: action["arguments"][name] for _, name, _ in self.arguments()[tool]}
        return json.dumps({"name": action["name"], "arguments": args}, ensure_ascii=False)


def _invert(mapping):
    return {v: k for k, v in mapping.items()}
