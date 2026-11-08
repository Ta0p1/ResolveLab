"""SQLite store of a durable CaseDesk episode, and the fault ledger the crash points consult.

One database file holds the service state (records, idempotency receipts, rate-limit window),
the environment state (virtual clock, permission, consumed faults, the oracle's expected
records) and the append-only audit the graders read (HTTP events, commits, reads,
escalations, process boots). It runs in WAL mode with ``synchronous=FULL``, and every request
is one ``BEGIN IMMEDIATE`` transaction, so writers in different processes are serialized by
SQLite itself and a commit is on disk before its response is built.

The fault ledger is a second database file. A crash point claims its fault there, in its own
transaction, before the process dies; that keeps the claim when the request's own transaction
is about to be lost, and lets each crash fire exactly once across workers.
"""

import copy
import json
import sqlite3
from pathlib import Path

STORES = ("durable", "process")

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE tickets (position INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, row TEXT NOT NULL);
CREATE TABLE receipts (
    idempotency_key TEXT PRIMARY KEY,
    signature TEXT NOT NULL,
    response TEXT NOT NULL,
    commit_seq INTEGER NOT NULL
);
CREATE TABLE commits (
    seq INTEGER PRIMARY KEY,
    ticket_id TEXT NOT NULL,
    before TEXT NOT NULL,
    after TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    boot INTEGER NOT NULL
);
CREATE TABLE reads (
    seq INTEGER PRIMARY KEY,
    ticket_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    after_commits INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    boot INTEGER NOT NULL
);
CREATE TABLE events (
    seq INTEGER PRIMARY KEY,
    event TEXT NOT NULL,
    commits_seen INTEGER NOT NULL,
    delivered INTEGER NOT NULL,
    boot INTEGER NOT NULL
);
CREATE TABLE escalations (seq INTEGER PRIMARY KEY, reason TEXT NOT NULL, boot INTEGER NOT NULL);
CREATE TABLE boots (
    boot INTEGER PRIMARY KEY,
    worker INTEGER,
    kind TEXT NOT NULL,
    pid INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    commits_seen INTEGER NOT NULL,
    recovered TEXT NOT NULL,
    exit_code INTEGER,
    ended_by TEXT
);
"""

LEDGER_SCHEMA = """
CREATE TABLE faults (
    name TEXT PRIMARY KEY,
    fired_boot INTEGER,
    fired_worker INTEGER,
    detail TEXT
);
"""

# Never read back after the episode starts.
STATIC = ("spec", "task", "reference", "target", "desired", "faults", "factors", "initial", "store")
# Read and written by every request, whichever store backs the records.
ENVIRONMENT = ("expected", "clock", "write_allowed", "consumed")


def connect(path):
    """A connection that waits for the write lock instead of failing, and syncs every commit."""
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def dumps(value):
    return json.dumps(value, sort_keys=True)


def create_store(path, world, spec, store):
    """Write a fresh episode from a ``WorldState``; the records are the ones it generated."""
    if store not in STORES:
        raise ValueError(f"Unknown store {store!r}; use one of {', '.join(STORES)}")
    conn = connect(path)
    try:
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if mode.lower() != "wal":
            raise RuntimeError(f"SQLite refused WAL mode ({mode})")
        conn.executescript(SCHEMA)
        conn.execute("BEGIN IMMEDIATE")
        meta = {
            "spec": spec,
            "task": world.task,
            "reference": world.reference,
            "target": world.target,
            "desired": world.desired,
            "faults": sorted(world.faults),
            "factors": world.factors,
            "initial": world.initial,
            "store": store,
            "expected": world.expected,
            "clock": world.clock,
            "write_allowed": world.write_allowed,
            "consumed": sorted(world.consumed),
            "retry_at": world.retry_at,
        }
        conn.executemany("INSERT INTO meta VALUES (?, ?)", [(k, dumps(v)) for k, v in meta.items()])
        conn.executemany(
            "INSERT INTO tickets VALUES (?, ?, ?)",
            [(i, key, dumps(row)) for i, (key, row) in enumerate(world.tickets.items())],
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


def create_ledger(path, faults):
    conn = connect(path)
    try:
        conn.executescript(LEDGER_SCHEMA)
        conn.executemany("INSERT INTO faults (name) VALUES (?)", [(name,) for name in sorted(faults)])
    finally:
        conn.close()


class Ledger:
    """Which planned faults have fired. A claim succeeds once, in whichever process asks first."""

    def __init__(self, path):
        self.conn = connect(path)

    def claim(self, name, boot, worker=None, detail=None):
        cursor = self.conn.execute(
            "UPDATE faults SET fired_boot = ?, fired_worker = ?, detail = ? "
            "WHERE name = ? AND fired_boot IS NULL",
            (boot, worker, detail, name),
        )
        return cursor.rowcount == 1

    def armed(self, name):
        row = self.conn.execute("SELECT fired_boot FROM faults WHERE name = ?", (name,)).fetchone()
        return row is not None and row[0] is None

    def rows(self):
        cursor = self.conn.execute("SELECT name, fired_boot, fired_worker, detail FROM faults")
        return [dict(zip(("name", "fired_boot", "fired_worker", "detail"), r)) for r in cursor]

    def close(self):
        self.conn.close()


def read_meta(conn, keys=None):
    rows = conn.execute("SELECT key, value FROM meta").fetchall()
    meta = {key: json.loads(value) for key, value in rows}
    return meta if keys is None else {key: meta[key] for key in keys}


def write_meta(conn, values):
    conn.executemany(
        "UPDATE meta SET value = ? WHERE key = ?", [(dumps(v), k) for k, v in values.items()]
    )


def read_tickets(conn):
    rows = conn.execute("SELECT id, row FROM tickets ORDER BY position").fetchall()
    return {key: json.loads(row) for key, row in rows}


def read_receipts(conn):
    rows = conn.execute("SELECT idempotency_key, signature, response FROM receipts ORDER BY rowid")
    return {key: {"signature": json.loads(s), "response": json.loads(r)} for key, s, r in rows}


def recovered(conn, meta):
    """The service state a process starts from: what the store kept, or nothing (``process``)."""
    if meta["store"] == "durable":
        return read_tickets(conn), read_receipts(conn), meta["retry_at"]
    return copy.deepcopy(meta["initial"]), {}, 0


def restarts(conn):
    return conn.execute("SELECT COUNT(*) FROM boots WHERE kind = 'restart'").fetchone()[0]


def commit_count(conn):
    return conn.execute("SELECT COUNT(*) FROM commits").fetchone()[0]


def register_boot(conn, boot, worker, kind, pid):
    """Record a process start and the record versions it recovered, atomically with the audit."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        meta = read_meta(conn)
        tickets, receipts, retry_at = recovered(conn, meta)
        if meta["store"] == "process":
            # The process store has nothing to recover; the table only mirrors what it serves.
            conn.executemany(
                "UPDATE tickets SET row = ? WHERE id = ?", [(dumps(t), k) for k, t in tickets.items()]
            )
        conn.execute(
            "INSERT INTO boots (boot, worker, kind, pid, epoch, commits_seen, recovered) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                boot,
                worker,
                kind,
                pid,
                restarts(conn) + (kind == "restart"),
                commit_count(conn),
                dumps({key: row["version"] for key, row in tickets.items()}),
            ),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return meta, tickets, receipts, retry_at


def end_boot(conn, boot, exit_code, ended_by):
    conn.execute(
        "UPDATE boots SET exit_code = ?, ended_by = ? WHERE boot = ? AND ended_by IS NULL",
        (exit_code, ended_by, boot),
    )


class Snapshot:
    """Server truth for the graders: the attributes grader v2 reads, plus boots and the ledger.

    ``tickets`` is the state recovered by the episode's final boot, so a grade is always of
    what survives a restart; ``served`` is what the service last wrote to its table.
    """

    def __init__(self, path, ledger_path):
        conn = connect(path)
        try:
            meta = read_meta(conn)
            for key in STATIC + ENVIRONMENT:
                setattr(self, key, meta[key])
            self.faults = set(meta["faults"])
            self.served = read_tickets(conn)
            self.tickets = recovered(conn, meta)[0]
            self.boots = [
                {
                    "boot": boot,
                    "worker": worker,
                    "kind": kind,
                    "pid": pid,
                    "epoch": epoch,
                    "commits_seen": seen,
                    "recovered": json.loads(versions),
                    "exit_code": code,
                    "ended_by": ended,
                }
                for boot, worker, kind, pid, epoch, seen, versions, code, ended in conn.execute(
                    "SELECT * FROM boots ORDER BY boot"
                )
            ]
            self.commits = [
                {
                    "seq": seq,
                    "id": key,
                    "before": json.loads(before),
                    "after": json.loads(after),
                    "key": idem,
                    "boot": boot,
                }
                for seq, key, before, after, idem, boot in conn.execute(
                    "SELECT * FROM commits ORDER BY seq"
                )
            ]
            self.reads = [
                {"seq": seq, "id": key, "version": v, "after_commits": n, "epoch": epoch, "boot": boot}
                for seq, key, v, n, epoch, boot in conn.execute("SELECT * FROM reads ORDER BY seq")
            ]
            self.http_events = [
                {
                    **json.loads(event),
                    "seq": seq,
                    "commits_seen": seen,
                    "delivered": bool(d),
                    "boot": boot,
                }
                for seq, event, seen, d, boot in conn.execute("SELECT * FROM events ORDER BY seq")
            ]
            self.escalations = [
                r for (r,) in conn.execute("SELECT reason FROM escalations ORDER BY seq")
            ]
            self.receipts = read_receipts(conn)
        finally:
            conn.close()
        ledger = Ledger(ledger_path)
        try:
            self.chaos = ledger.rows()
        finally:
            ledger.close()
        fired = {row["name"] for row in self.chaos if row["fired_boot"] is not None}
        self.consumed = set(self.consumed) | fired
        self.path = Path(path)
