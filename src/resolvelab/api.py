import json
import os
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .evaluation import evaluate, export_trace, new_report, write_report
from .runner import Runner
from .scenarios import BY_ID, SCENARIOS
from .store import Store

STATIC = Path(__file__).parent / "static"
ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class RunRequest(BaseModel):
    scenario: str
    policy: Literal["reference", "naive", "ollama"] = "reference"
    seed: int = Field(default=42, ge=0, le=1000000)
    model: str = Field(default="qwen3:4b", min_length=1, max_length=120)


class EvalRequest(BaseModel):
    policies: list[Literal["reference", "naive", "ollama"]] = Field(
        default=["naive", "reference"], min_length=1, max_length=3
    )
    suite: Literal["full", "smoke"] = "full"
    seed: int = Field(default=42, ge=0, le=1000000)
    model: str = Field(default="qwen3:4b", min_length=1, max_length=120)


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    root = Path(data_dir or os.getenv("RESOLVELAB_DATA_DIR", ".local"))
    store = Store(root / "resolvelab.sqlite")
    runner = Runner(store)
    eval_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        store.recover_interrupted()
        reports = root / "reports"
        if reports.exists():
            for path in reports.glob("*.json"):
                report = json.loads(path.read_text(encoding="utf-8"))
                if report.get("status") == "running":
                    report["status"] = "interrupted"
                    write_report(path, report)
        yield

    app = FastAPI(title="ResolveLab", version=__version__, lifespan=lifespan)
    app.state.store, app.state.runner = store, runner

    @app.middleware("http")
    async def local_origin_guard(request: Request, call_next):
        # Local unauthenticated app: reject cross-origin mutation from websites.
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin != expected:
            return JSONResponse({"detail": "Cross-origin mutations are disabled."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def get_run(run_id):
        if not ID_PATTERN.fullmatch(run_id):
            raise HTTPException(404, "Unknown run")
        try:
            return store.get(run_id)
        except KeyError:
            raise HTTPException(404, "Unknown run") from None

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/api/scenarios")
    def scenarios():
        return [s.public() for s in SCENARIOS]

    @app.get("/api/models")
    def models():
        url = os.getenv("RESOLVELAB_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                response = client.get(url + "/api/tags")
                response.raise_for_status()
                names = [m["name"] for m in response.json().get("models", [])]
            return {"available": True, "models": names}
        except (httpx.HTTPError, ValueError):
            return {"available": False, "models": []}

    @app.get("/api/runs")
    def runs():
        return store.list_runs()

    @app.post("/api/runs", status_code=201)
    def start_run(body: RunRequest):
        if body.scenario not in BY_ID:
            raise HTTPException(422, "Unknown scenario")
        run_id = store.create(
            body.scenario, body.seed, body.policy, body.model if body.policy == "ollama" else None
        )
        runner.start(run_id)
        return {"id": run_id}

    @app.get("/api/runs/{run_id}")
    def read_run(run_id: str):
        return get_run(run_id)

    @app.post("/api/runs/{run_id}/resume")
    def resume(run_id: str):
        run = get_run(run_id)
        if run["status"] != "interrupted":
            raise HTTPException(409, "Only an interrupted run can resume.")
        return {"started": runner.start(run_id), "id": run_id}

    @app.get("/api/runs/{run_id}/trace")
    def trace(run_id: str):
        get_run(run_id)
        return Response(
            export_trace(store, run_id),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="resolvelab-{run_id[:8]}.jsonl"'},
        )

    @app.get("/api/evaluations")
    def reports():
        paths = sorted((root / "reports").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [json.loads(p.read_text(encoding="utf-8")) for p in paths[:20]]

    @app.post("/api/evaluations", status_code=201)
    def start_eval(body: EvalRequest):
        if not eval_lock.acquire(blocking=False):
            raise HTTPException(409, "An evaluation is already running.")
        scenario_ids = (
            ["partial_sync", "lost_response", "read_only"] if body.suite == "smoke" else list(BY_ID)
        )
        try:
            report = new_report(
                list(dict.fromkeys(body.policies)), scenario_ids, [body.seed], body.model
            )
            path = root / "reports" / f"{report['id']}.json"
            write_report(path, report)
        except Exception:
            eval_lock.release()
            raise

        def worker():
            try:
                evaluate(runner, report, path, body.model)
            finally:
                eval_lock.release()

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception:
            eval_lock.release()
            raise
        return {"id": report["id"]}

    @app.get("/api/evaluations/{report_id}")
    def read_report(report_id: str):
        if not ID_PATTERN.fullmatch(report_id):
            raise HTTPException(404, "Unknown evaluation")
        path = root / "reports" / f"{report_id}.json"
        if not path.exists():
            raise HTTPException(404, "Unknown evaluation")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
