"""The episode log: one JSON object per line, in the order things happened.

    {"type": "header", "format": "resolvelab-proxy-log/1", "scenario": {...}, "seed": 0, ...}
    {"type": "probe", "phase": "before", "responses": [...]}
    {"type": "request", "seq": 1, "clock": 0, "method": "POST", "path": "/orders/7/refund", ...}
    {"type": "fault", "seq": 1, "fault": 0, "kind": "lost_ack", "stage": "after", ...}
    {"type": "upstream", "seq": 1, "status": 201, ...}
    {"type": "response", "seq": 1, "status": 502, ...}
    {"type": "wait", "seconds": 2, "clock": 2}
    {"type": "finish", "outcome": "resolved", "summary": "..."}
    {"type": "probe", "phase": "after", "responses": [...]}
    {"type": "end", "reason": "finish"}

``request`` is what the agent sent, ``upstream`` what the service answered (absent when a
fault answered instead), ``response`` what the agent received. The header carries the whole
effective scenario, so a log is graded and replayed with nothing else. There are no wall-clock
times: the same scenario, seed and agent actions give the same lines.

Bodies are stored as parsed JSON when they parse (``json``), otherwise as UTF-8 ``text`` or
``base64``. Credentials are never written: headers named in the scenario's ``redact_headers``
are logged as ``[redacted]``, and hop-by-hop, ``date`` and ``server`` headers are left out.
"""

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

FORMAT = "resolvelab-proxy-log/1"
REDACTED = "[redacted]"
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
# Recomputed by each hop, or different on every run.
UNLOGGED = HOP_BY_HOP | {
    "host",
    "content-length",
    "content-encoding",
    "accept-encoding",
    "date",
    "server",
}


@dataclass
class Request:
    method: str
    path: str
    query: str = ""
    headers: dict = field(default_factory=dict)  # lower-case names
    body: bytes = b""

    @property
    def target(self):
        return self.path + (f"?{self.query}" if self.query else "")

    def header(self, name):
        return self.headers.get(name.lower())


@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)  # lower-case names
    body: bytes = b""

    @classmethod
    def json(cls, status, value, headers=None):
        content = json.dumps(value, sort_keys=True).encode()
        return cls(status, {"content-type": "application/json", **(headers or {})}, content)


def lower_headers(pairs):
    """Lower-case names; a repeated header keeps its values joined with ', '."""
    merged = {}
    for name, value in pairs:
        name = name.lower()
        merged[name] = f"{merged[name]}, {value}" if name in merged else value
    return merged


def logged_headers(headers, redact):
    return {
        name: REDACTED if name in redact else value
        for name, value in sorted(headers.items())
        if name not in UNLOGGED
    }


def encode_body(content):
    if not content:
        return {}
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return {"base64": base64.b64encode(content).decode("ascii")}
    try:
        return {"json": json.loads(text)}
    except ValueError:
        return {"text": text}


def decode_body(record):
    if "json" in record:
        return json.dumps(record["json"]).encode()
    if "text" in record:
        return record["text"].encode("utf-8")
    if "base64" in record:
        return base64.b64decode(record["base64"])
    return b""


def body_value(record):
    """The parsed JSON body of a logged request or response, or None."""
    return record.get("json")


class EpisodeLog:
    """Records kept in memory and, with a path, appended to a JSONL file as they happen."""

    def __init__(self, path=None):
        self.records = []
        self.path = Path(path) if path else None
        self._file = None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open("w", encoding="utf-8", newline="\n")

    def write(self, record):
        self.records.append(record)
        if self._file is not None:
            self._file.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
            self._file.flush()

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None


def read_log(source):
    """Records from a log path or an iterable of records; checks the header."""
    if isinstance(source, (str, Path)):
        lines = Path(source).read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
    else:
        records = list(source)
    if not records or records[0].get("type") != "header":
        raise ValueError("Not a proxy episode log: the first record is not a header")
    if records[0].get("format") != FORMAT:
        raise ValueError(f"Unsupported log format {records[0].get('format')!r}; expected {FORMAT}")
    return records
