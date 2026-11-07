"""One CaseDesk worker process: recover from the episode's store, then serve it over uvicorn.

    python -m resolvelab.durable.worker --dir EPISODE_DIR --worker 0 --boot 1 --kind start

The supervisor (``durable.desk``) starts these; a person rarely needs to. The worker binds
a free loopback port, records its boot and the record versions it recovered, writes
``ready-<boot>.json`` with its port, and serves until it is killed or reaches a crash point.
"""

import argparse
import json
import os
import socket
import sys
from pathlib import Path

import uvicorn

from ..httpdesk.service import create_app
from .service import PersistedState
from .store import connect, register_boot

DATABASE, LEDGER = "desk.sqlite", "chaos.sqlite"


def ready_file(directory, boot):
    return Path(directory) / f"ready-{boot}.json"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m resolvelab.durable.worker")
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--worker", type=int, required=True)
    parser.add_argument("--boot", type=int, required=True)
    parser.add_argument("--kind", choices=["start", "restart"], required=True)
    parser.add_argument("--hold-ms", type=int, default=0)
    args = parser.parse_args(argv)

    conn = connect(args.dir / DATABASE)
    try:
        _, tickets, receipts, retry_at = register_boot(
            conn, args.boot, args.worker, args.kind, os.getpid()
        )
    finally:
        conn.close()
    state = PersistedState(
        args.dir / DATABASE,
        args.dir / LEDGER,
        worker=args.worker,
        boot=args.boot,
        recovered=(tickets, receipts, retry_at),
        hold_ms=args.hold_ms,
    )
    app = create_app(state)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    # Connections queue in the backlog from here on, so the supervisor may connect right away.
    ready = ready_file(args.dir, args.boot)
    partial = ready.with_suffix(".tmp")
    partial.write_text(json.dumps({"port": sock.getsockname()[1], "pid": os.getpid()}), encoding="utf-8")
    os.replace(partial, ready)
    config = uvicorn.Config(app, log_level="error", access_log=False, lifespan="off")
    uvicorn.Server(config).run(sockets=[sock])
    return 0


if __name__ == "__main__":
    sys.exit(main())
