"""SQLite persistence; each tool action, receipt and trace event commits atomically."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .scenarios import BY_ID, TASK, make_records


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS runs(
              id TEXT PRIMARY KEY, scenario TEXT NOT NULL, seed INTEGER NOT NULL,
              policy TEXT NOT NULL, model TEXT, status TEXT NOT NULL,
              state TEXT NOT NULL, messages TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              verdict TEXT, claim TEXT, summary TEXT, error TEXT,
              wall_seconds REAL NOT NULL DEFAULT 0,
              input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS source(
              run_id TEXT NOT NULL, record_id TEXT NOT NULL, body TEXT NOT NULL,
              PRIMARY KEY(run_id, record_id)
            );
            CREATE TABLE IF NOT EXISTS destination(
              row_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
              record_id TEXT NOT NULL, body TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS dest_run ON destination(run_id, record_id);
            CREATE TABLE IF NOT EXISTS receipts(
              run_id TEXT NOT NULL, key TEXT NOT NULL, signature TEXT NOT NULL, result TEXT NOT NULL,
              PRIMARY KEY(run_id, key)
            );
            CREATE TABLE IF NOT EXISTS events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, kind TEXT NOT NULL,
              name TEXT NOT NULL, arguments TEXT NOT NULL, result TEXT NOT NULL,
              duration_ms REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS event_run ON events(run_id, id);
            """)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=20)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def create(
        self, scenario: str, seed: int = 42, policy: str = "reference", model: str | None = None
    ) -> str:
        spec = BY_ID[scenario]
        records = make_records(seed)
        run_id = uuid.uuid4().hex
        initial = records[: len(records) // 3]
        if "corrupt" in spec.faults:
            initial = [dict(r) for r in initial]
            initial[0]["amount_cents"] += 999
        state = {
            "key_field": "legacy_id" if "mapping" in spec.faults else "record_id",
            "write_allowed": "readonly" not in spec.faults,
            "job_status": "completed" if "stale" in spec.faults else "failed",
            "clock": 0,
            "retry_at": 3 if "rate" in spec.faults else 0,
            "fault_consumed": False,
            "escalation": None,
            "initial_destination": initial,
            "initial_key_field": "legacy_id" if "mapping" in spec.faults else "record_id",
        }
        now = utcnow()
        with self.connect() as c:
            c.execute(
                "INSERT INTO runs(id,scenario,seed,policy,model,status,state,created_at,updated_at) "
                "VALUES(?,?,?,?,?,'queued',?,?,?)",
                (run_id, scenario, seed, policy, model, dumps(state), now, now),
            )
            c.executemany(
                "INSERT INTO source VALUES(?,?,?)", [(run_id, r["record_id"], dumps(r)) for r in records]
            )
            c.executemany(
                "INSERT INTO destination(run_id,record_id,body) VALUES(?,?,?)",
                [(run_id, r["record_id"], dumps(r)) for r in initial],
            )
        return run_id

    def get(self, run_id: str, *, events: bool = True) -> dict:
        with self.connect() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            result = dict(row)
            for key in ("state", "messages", "verdict"):
                result[key] = json.loads(result[key]) if result[key] is not None else None
            result["task"] = TASK
            result["scenario_info"] = BY_ID[row["scenario"]].public()
            result["source_count"] = c.execute(
                "SELECT COUNT(*) FROM source WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            result["destination_count"] = c.execute(
                "SELECT COUNT(*) FROM destination WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            result["tool_count"] = c.execute(
                "SELECT COUNT(*) FROM events WHERE run_id=? AND kind='tool'", (run_id,)
            ).fetchone()[0]
            if events:
                result["events"] = [
                    {
                        **dict(e),
                        "arguments": json.loads(e["arguments"]),
                        "result": json.loads(e["result"]),
                    }
                    for e in c.execute("SELECT * FROM events WHERE run_id=? ORDER BY id", (run_id,))
                ]
            return result

    def list_runs(self, limit: int = 40) -> list[dict]:
        with self.connect() as c:
            ids = [
                r[0] for r in c.execute("SELECT id FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))
            ]
        return [self.get(i, events=False) for i in ids]

    def update(self, run_id: str, **fields):
        allowed = {
            "status",
            "messages",
            "verdict",
            "claim",
            "summary",
            "error",
            "wall_seconds",
            "input_tokens",
            "output_tokens",
        }
        if not fields or not fields.keys() <= allowed:
            raise ValueError("Invalid run update")
        fields = {k: dumps(v) if k in {"messages", "verdict"} else v for k, v in fields.items()}
        fields["updated_at"] = utcnow()
        with self.connect() as c:
            c.execute(
                f"UPDATE runs SET {','.join(k + '=?' for k in fields)} WHERE id=?",
                (*fields.values(), run_id),
            )

    def event(
        self, run_id: str, kind: str, name: str, arguments: dict, result: dict, duration_ms: float = 0
    ):
        with self.connect() as c:
            self.insert_event(c, run_id, kind, name, arguments, result, duration_ms)

    @staticmethod
    def insert_event(c, run_id, kind, name, arguments, result, duration_ms=0):
        c.execute(
            "INSERT INTO events(run_id,kind,name,arguments,result,duration_ms,created_at) VALUES(?,?,?,?,?,?,?)",
            (run_id, kind, name, dumps(arguments), dumps(result), duration_ms, utcnow()),
        )

    def recover_interrupted(self):
        with self.connect() as c:
            c.execute(
                "UPDATE runs SET status='interrupted',updated_at=? WHERE status IN ('running','queued')",
                (utcnow(),),
            )
