"""The frozen CaseDesk handlers, run on state that lives in SQLite instead of process memory.

``httpdesk.service.create_app`` does every read and write of a request inside
``with state.lock:``. Here that lock is a database transaction: entering it takes SQLite's
write lock (``BEGIN IMMEDIATE``, which also serializes other worker processes) and loads the
state; leaving it writes back what the handler changed and commits. The endpoints, status
codes, ETags, receipts and fault behaviour are the v0.3 code, unchanged and imported.

Crash points sit on that commit, for a request that committed a ticket write:

- ``crash_before_commit``: the writes are staged in the open transaction, then the process
  exits. SQLite discards the uncommitted transaction; the client gets no response.
- ``crash_after_commit``: the transaction commits, then the process exits before the handler
  returns, so the response is never sent. The HTTP event is stored as not delivered.

Both exit through ``os._exit``: no ``finally`` blocks, no flush, no shutdown handlers.

With ``store="process"`` the records, receipts and rate-limit window stay in process memory,
starting from the initial records at every boot, as the v0.3 service does; only the
environment and the audit go to SQLite. It is the negative control for the durable grader.
"""

import json
import os
import threading
import time

from ..httpdesk.service import DeskState
from .store import ENVIRONMENT, Ledger, connect, dumps, read_meta, read_receipts, read_tickets, restarts

EXIT_CODES = {"crash_before_commit": 70, "crash_after_commit": 71}


class Transaction:
    """``state.lock`` for the frozen handlers: one SQLite write transaction per request."""

    def __init__(self, state):
        self.state = state
        self.mutex = threading.Lock()

    def __enter__(self):
        self.mutex.acquire()
        try:
            self.state.begin()
        except BaseException:
            self.mutex.release()
            raise
        return self

    def __exit__(self, kind, exc, tb):
        try:
            if kind is None:
                try:
                    self.state.commit()
                except BaseException:
                    self.state.rollback()
                    raise
            else:
                self.state.rollback()
        finally:
            self.mutex.release()


class PersistedState(DeskState):
    """A ``DeskState`` whose attributes are loaded from SQLite around each request."""

    def __init__(self, path, ledger_path, *, worker, boot, recovered, hold_ms=0):
        self.conn = connect(path)
        self.ledger = Ledger(ledger_path)
        meta = read_meta(self.conn)
        self.store = meta["store"]
        self.spec, self.task, self.reference = meta["spec"], meta["task"], meta["reference"]
        self.target, self.desired, self.factors = meta["target"], meta["desired"], meta["factors"]
        self.faults, self.initial = set(meta["faults"]), meta["initial"]
        self.worker, self.boot, self.hold_ms = worker, boot, hold_ms
        # Service state the process started with; the durable store reloads it per request.
        self.tickets, self.receipts, self.retry_at = recovered
        self.lock = Transaction(self)

    def begin(self):
        conn = self.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            meta = read_meta(conn)
            self.expected, self.clock = meta["expected"], meta["clock"]
            self.write_allowed, self.consumed = meta["write_allowed"], set(meta["consumed"])
            if self.store == "durable":
                self.tickets, self.receipts = read_tickets(conn), read_receipts(conn)
                self.retry_at = meta["retry_at"]
            self.http_events = [
                json.loads(e) for (e,) in conn.execute("SELECT event FROM events ORDER BY seq")
            ]
            self.commits = [
                {"id": key, "before": json.loads(before), "after": json.loads(after)}
                for key, before, after in conn.execute(
                    "SELECT ticket_id, before, after FROM commits ORDER BY seq"
                )
            ]
            self.reads = [
                {"id": key, "version": version, "after_commits": seen}
                for key, version, seen in conn.execute(
                    "SELECT ticket_id, version, after_commits FROM reads ORDER BY seq"
                )
            ]
            self.escalations = [
                r for (r,) in conn.execute("SELECT reason FROM escalations ORDER BY seq")
            ]
            self.epoch = restarts(conn)
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        self.mark = {
            "events": len(self.http_events),
            "commits": len(self.commits),
            "reads": len(self.reads),
            "escalations": len(self.escalations),
            "receipts": set(self.receipts),
        }

    def commit(self):
        conn, mark = self.conn, self.mark
        new_commits = self.commits[mark["commits"] :]
        new_keys = [key for key in self.receipts if key not in mark["receipts"]]
        if len(new_keys) != len(new_commits):
            raise RuntimeError("Every committed write must store exactly one idempotency receipt")
        seen = len(self.commits)
        for event in self.http_events[mark["events"] :]:
            conn.execute(
                "INSERT INTO events (event, commits_seen, delivered, boot) VALUES (?, ?, 1, ?)",
                (dumps(event), seen, self.boot),
            )
        for commit, key in zip(new_commits, new_keys):
            seq = conn.execute(
                "INSERT INTO commits (ticket_id, before, after, idempotency_key, boot) VALUES (?, ?, ?, ?, ?)",
                (commit["id"], dumps(commit["before"]), dumps(commit["after"]), key, self.boot),
            ).lastrowid
            if self.store == "durable":
                receipt = self.receipts[key]
                conn.execute(
                    "INSERT INTO receipts VALUES (?, ?, ?, ?)",
                    (key, dumps(receipt["signature"]), dumps(receipt["response"]), seq),
                )
        for read in self.reads[mark["reads"] :]:
            conn.execute(
                "INSERT INTO reads (ticket_id, version, after_commits, epoch, boot) VALUES (?, ?, ?, ?, ?)",
                (read["id"], read["version"], read["after_commits"], self.epoch, self.boot),
            )
        for reason in self.escalations[mark["escalations"] :]:
            conn.execute("INSERT INTO escalations (reason, boot) VALUES (?, ?)", (reason, self.boot))
        conn.executemany(
            "UPDATE tickets SET row = ? WHERE id = ?", [(dumps(t), k) for k, t in self.tickets.items()]
        )
        values = {key: getattr(self, key) for key in ENVIRONMENT}
        values["consumed"] = sorted(self.consumed)
        if self.store == "durable":
            values["retry_at"] = self.retry_at
        conn.executemany(
            "UPDATE meta SET value = ? WHERE key = ?", [(dumps(v), k) for k, v in values.items()]
        )
        if new_commits:
            self.crash_point("crash_before_commit")
            if self.hold_ms:
                # Widen the window in which another worker waits on the write lock (race tests).
                time.sleep(self.hold_ms / 1000)
            if self.claim("crash_after_commit"):
                conn.execute("UPDATE events SET delivered = 0 WHERE seq = (SELECT MAX(seq) FROM events)")
                conn.execute("COMMIT")
                os._exit(EXIT_CODES["crash_after_commit"])
        conn.execute("COMMIT")

    def rollback(self):
        if self.conn.in_transaction:
            self.conn.execute("ROLLBACK")

    def claim(self, fault):
        return fault in self.faults and self.ledger.claim(fault, self.boot, self.worker)

    def crash_point(self, fault):
        if self.claim(fault):
            os._exit(EXIT_CODES[fault])
