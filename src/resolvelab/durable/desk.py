"""Supervisor and transport: worker processes on one store, restarted when they die.

``DurableDesk`` creates an episode's store from its spec, starts one or two uvicorn worker
processes on it, and plays the orchestrator: a worker that died is restarted on the same store
once a request has failed against it, and ``restart_after_commit`` kills every worker after the
first committing request. Closing the desk kills the workers outright, then recovers the store
once more in this process, so the graders always judge the state that survives a restart.

``DurableAdapter`` is the CaseDesk ``DeskAdapter`` with a client that routes requests round-robin
over the workers' current addresses; the agent never sees ports or worker numbers.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

import resolvelab

from ..casedesk.world import WorldState
from ..httpdesk.adapter import DeskAdapter
from .episodes import PROCESS_FAULTS, validate_spec
from .service import EXIT_CODES
from .store import (
    Ledger,
    Snapshot,
    commit_count,
    connect,
    create_ledger,
    create_store,
    end_boot,
    register_boot,
)
from .worker import DATABASE, LEDGER, ready_file

START_TIMEOUT = 30
EXIT_WAIT = 5
ENDED_BY = {code: fault for fault, code in EXIT_CODES.items()}


class WorkerProcess:
    def __init__(self, process, pid, boot, url, log):
        self.process, self.pid, self.boot, self.url, self.log = process, pid, boot, url, log


class DurableDesk:
    def __init__(self, spec, *, store="durable", hold_ms=0, directory=None):
        self.spec = validate_spec(spec)
        self.store, self.hold_ms = store, hold_ms
        self.workers = spec.get("workers", 1)
        self.keep = directory is not None
        self.directory = Path(directory) if directory else None
        self.processes, self.urls, self.history = {}, {}, []
        self.next_boot = 1
        self.snapshot = None

    # -- lifecycle -------------------------------------------------------------------------

    def __enter__(self):
        if self.directory is None:
            self.directory = Path(tempfile.mkdtemp(prefix="resolvelab-durable-"))
        else:
            self.directory.mkdir(parents=True, exist_ok=False)
        world = WorldState(self.spec)
        self.task = world.task
        create_store(self.directory / DATABASE, world, self.spec, self.store)
        create_ledger(self.directory / LEDGER, set(self.spec["faults"]) & PROCESS_FAULTS)
        self.ledger = Ledger(self.directory / LEDGER)
        try:
            for worker in range(self.workers):
                self.start(worker, "start")
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        """Kill every worker, recover the store in this process and keep that as the truth."""
        if self.snapshot is not None:
            return self.snapshot
        for worker in list(self.processes):
            self.kill(worker, ended_by="stopped")
        conn = connect(self.directory / DATABASE)
        try:
            register_boot(conn, self.next_boot, None, "final", os.getpid())
        finally:
            conn.close()
        self.ledger.close()
        self.snapshot = Snapshot(self.directory / DATABASE, self.directory / LEDGER)
        if not self.keep:
            shutil.rmtree(self.directory, ignore_errors=True)
        return self.snapshot

    # -- processes -------------------------------------------------------------------------

    def start(self, worker, kind):
        boot, self.next_boot = self.next_boot, self.next_boot + 1
        log = open(self.directory / f"worker-{worker}-boot-{boot}.log", "wb")
        package_root = str(Path(resolvelab.__file__).resolve().parents[1])
        path = os.pathsep.join(filter(None, [package_root, os.environ.get("PYTHONPATH", "")]))
        command = [
            sys.executable,
            "-m",
            "resolvelab.durable.worker",
            "--dir",
            str(self.directory),
            "--worker",
            str(worker),
            "--boot",
            str(boot),
            "--kind",
            kind,
            "--hold-ms",
            str(self.hold_ms),
        ]
        process = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, env=os.environ | {"PYTHONPATH": path}
        )
        ready = ready_file(self.directory, boot)
        deadline = time.monotonic() + START_TIMEOUT
        while not ready.exists():
            if process.poll() is not None or time.monotonic() > deadline:
                process.kill()
                process.wait()
                log.close()
                output = Path(log.name).read_text(encoding="utf-8", errors="replace")
                raise RuntimeError(f"CaseDesk worker {worker} failed to start:\n{output[-2000:]}")
            time.sleep(0.01)
        info = json.loads(ready.read_text(encoding="utf-8"))
        url = f"http://127.0.0.1:{info['port']}"
        self.processes[worker] = WorkerProcess(process, info["pid"], boot, url, log)
        self.urls[worker] = self.processes[worker].url
        self.history.append({"worker": worker, "boot": boot, "kind": kind})
        return boot

    def kill(self, worker, ended_by="killed"):
        """Kill a worker process outright (SIGKILL / TerminateProcess) and record why it ended.

        The signal goes to the interpreter's own pid. On Windows a virtual environment's
        ``python.exe`` is a launcher whose child is the interpreter; killing the launcher ends
        the child only later, while it may still hold the store open. The launcher exits after
        its child, so waiting on it afterwards means the worker is really gone.
        """
        entry = self.processes.pop(worker)
        if entry.process.poll() is None:
            try:
                os.kill(entry.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
            except OSError:
                pass
            try:
                entry.process.wait(timeout=EXIT_WAIT)
            except subprocess.TimeoutExpired:
                entry.process.kill()
        code = entry.process.wait()
        entry.log.close()
        self.record_end(entry.boot, code, ended_by)

    def record_end(self, boot, code, ended_by):
        conn = connect(self.directory / DATABASE)
        try:
            end_boot(conn, boot, code, ended_by)
        finally:
            conn.close()

    def ensure_running(self):
        """Restart every worker that has died, on the same store. Returns the restarted workers."""
        restarted = []
        for worker in range(self.workers):
            entry = self.processes.get(worker)
            if entry is not None and entry.process.poll() is None:
                continue
            if entry is not None:
                del self.processes[worker]
                code = entry.process.wait()
                entry.log.close()
                self.record_end(entry.boot, code, ENDED_BY.get(code, "exited"))
            self.start(worker, "restart")
            restarted.append(worker)
        return restarted

    def kill_all(self, ended_by="killed"):
        for worker in list(self.processes):
            self.kill(worker, ended_by)

    def url(self, worker):
        """The worker's current address; a dead worker keeps its last one, which now refuses."""
        return self.urls.get(worker)

    def commit_count(self):
        conn = connect(self.directory / DATABASE)
        try:
            return commit_count(conn)
        finally:
            conn.close()

    # -- fault schedule --------------------------------------------------------------------

    def after_request(self, commits_before, unanswered_by=None):
        """Called after each agent request: restart the dead, then apply a scheduled restart.

        ``unanswered_by`` is the worker that sent no response. The client can see the dropped
        connection before the process has been reaped, so wait for it briefly: an orchestrator
        restarts on process exit, not on a client's error.
        """
        entry = self.processes.get(unanswered_by)
        if entry is not None:
            try:
                entry.process.wait(timeout=EXIT_WAIT)
            except subprocess.TimeoutExpired:
                pass
        restarted = self.ensure_running()
        if (
            "restart_after_commit" in self.spec["faults"]
            and self.commit_count() > commits_before
            and self.ledger.claim("restart_after_commit", self.next_boot - 1, detail="supervisor")
        ):
            self.kill_all()
        return restarted


class Router:
    """The ``httpx.Client`` surface ``DeskAdapter`` uses, spread over the desk's workers."""

    def __init__(self, desk, duplicate=False):
        self.desk, self.duplicate = desk, duplicate
        self.turn, self.last_worker = 0, None
        self.clients, self.duplicates = {}, []

    def client(self, worker):
        url = self.desk.url(worker)
        cached = self.clients.get(worker)
        if cached is None or cached[0] != url:
            if cached is not None:
                cached[1].close()
            self.clients[worker] = (url, httpx.Client(base_url=url, timeout=5, trust_env=False))
        return self.clients[worker][1]

    def request(self, method, path, **kwargs):
        worker = self.turn % self.desk.workers
        self.turn += 1
        self.last_worker = worker
        if not (self.duplicate and method == "PATCH" and self.desk.workers > 1):
            return self.client(worker).request(method, path, **kwargs)
        other = (worker + 1) % self.desk.workers
        clients = {worker: self.client(worker), other: self.client(other)}
        self.desk.ledger.claim("duplicate_delivery", self.desk.next_boot - 1, detail="router")
        barrier = threading.Barrier(2)

        def send(target):
            barrier.wait()
            return clients[target].request(method, path, **kwargs)

        with ThreadPoolExecutor(2) as pool:
            primary, second = pool.submit(send, worker), pool.submit(send, other)
            try:
                response = second.result()
                self.duplicates.append(
                    {"worker": other, "status": response.status_code, "body": response.json()}
                )
            except (httpx.HTTPError, ValueError) as exc:
                self.duplicates.append({"worker": other, "error": type(exc).__name__})
            return primary.result()

    def close(self):
        for _, client in self.clients.values():
            client.close()


class DurableAdapter(DeskAdapter):
    """The CaseDesk adapter, unchanged in what it sends and observes, over the router."""

    def __init__(self, desk, duplicate=False):
        self.client = Router(desk, duplicate)
        self.requests = []

    def dispatch(self, decision):
        before = len(self.requests)
        result = super().dispatch(decision)
        if len(self.requests) > before:
            self.requests[-1]["worker"] = self.client.last_worker
        return result
