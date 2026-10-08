"""The Growth Agent web app: a JSON API over the agent's tables, plus one static page.

Run from src/ with `python -m app.server` (Databricks Apps does this; see resources/app.yml)."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import queries
from chiro_agent.measure import INTERVENTION_COLUMN, RETURN_PROBABILITY
from app.live import LiveRuns, RunInProgress

STATIC = Path(__file__).parent / "static"
CLINIC_ID = re.compile(r"^LOC\d{3}$")
NETWORK_TTL = 120   # seconds; clinic KPIs only change when the nightly job rebuilds them
POLL_SECONDS = 10   # how long an events request waits for something new
# The outcome model's assumptions, shown on the Results tab: chance a patient comes back, by their
# hidden reason for stopping (rows) and the outreach they got (columns).
ASSUMPTIONS = {"reasons": list(RETURN_PROBABILITY), "interventions": list(INTERVENTION_COLUMN),
               "rows": [list(p) for p in RETURN_PROBABILITY.values()]}


@dataclass
class Backend:
    wh: Any
    fq: str
    model: str
    mlflow_url: str | None
    live: LiveRuns

    @classmethod
    def from_env(cls) -> "Backend":
        from databricks.sdk import WorkspaceClient

        from app.live import director_runner
        from chiro_agent.config import Settings
        from chiro_agent.db import Warehouse
        from chiro_agent.director import new_run_id

        settings, w = Settings.from_env(), WorkspaceClient()
        host = w.config.host.rstrip("/")
        url = f"{host}/ml/experiments/{settings.experiment_id}/traces" if settings.experiment_id else None
        return cls(Warehouse(w, settings.warehouse_id), settings.fq, settings.llm_endpoint, url,
                   LiveRuns(director_runner(settings, w), new_run_id))


class Decision(BaseModel):
    status: str
    message: str | None = None


class ApproveAll(BaseModel):
    run_id: str
    location_id: str | None = None  # None approves the whole run


class RunRequest(BaseModel):
    clinic: str
    patients: int = 4


def create_app(backend: Backend) -> FastAPI:
    api = FastAPI(title="Growth Agent", docs_url=None, redoc_url=None, openapi_url=None)
    cache: dict[str, tuple[float, dict]] = {}

    def network() -> dict:
        hit = cache.get("network")
        if hit and time.monotonic() - hit[0] < NETWORK_TTL:
            return hit[1]
        value = queries.network(backend.wh, backend.fq)
        cache["network"] = (time.monotonic(), value)
        return value

    @api.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        body = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
        return JSONResponse(body, status_code=exc.status_code)

    @api.exception_handler(RequestValidationError)
    async def bad_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
        return JSONResponse({"error": f"Invalid request: {problems}"}, status_code=400)

    @api.exception_handler(Exception)
    async def server_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"[:500]}, status_code=500)

    @api.middleware("http")
    async def no_stale_pages(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache"  # a redeploy must never mix old and new JS
        return response

    @api.get("/api/network")
    def get_network() -> dict:
        return network()

    @api.get("/api/clinics/{clinic_id}")
    def get_clinic(clinic_id: str, run_id: str | None = None) -> dict:
        if not CLINIC_ID.match(clinic_id):
            raise HTTPException(404, f"No clinic called {clinic_id}")
        try:
            return queries.clinic_story(backend.wh, backend.fq, clinic_id, run_id or None)
        except KeyError:
            raise HTTPException(404, f"No clinic called {clinic_id}") from None

    @api.post("/api/actions/approve-all")
    def post_approve_all(body: ApproveAll) -> dict:
        queries.approve_all(backend.wh, backend.fq, body.run_id, body.location_id)
        return {"ok": True}

    @api.post("/api/actions/{action_id}")
    def post_action(action_id: str, body: Decision) -> dict:
        try:
            queries.set_action(backend.wh, backend.fq, action_id, body.status, body.message)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return {"ok": True}

    @api.post("/api/runs")
    def post_run(body: RunRequest) -> dict:
        if body.clinic not in {c["id"] for c in network()["clinics"]}:
            raise HTTPException(400, f"No clinic called {body.clinic}")
        try:
            log = backend.live.start(body.clinic, min(8, max(2, body.patients)))
        except RunInProgress as busy:
            raise HTTPException(409, {"error": "A run is already in progress.", "run_id": busy.run_id,
                                      "clinic": busy.clinic}) from None
        return {"run_id": log.run_id}

    @api.get("/api/runs/{run_id}/events")
    def get_events(run_id: str, after: int = 0) -> dict:
        log = backend.live.get(run_id)
        if log is None:
            raise HTTPException(404, "This run isn't being tracked any more. Reload to see its results.")
        events, finished = log.wait(after, POLL_SECONDS)
        return {"events": events, "finished": finished}

    @api.get("/api/run")
    def get_run(run_id: str | None = None) -> dict:
        return queries.run_overview(backend.wh, backend.fq, run_id or None)

    @api.get("/api/runs/{run_id}/steps")
    def get_steps(run_id: str) -> dict:
        return {"steps": queries.run_steps(backend.wh, backend.fq, run_id)}

    @api.get("/api/meta")
    def get_meta() -> dict:
        active = backend.live.active()
        return {"model": backend.model, "mlflow_url": backend.mlflow_url, "assumptions": ASSUMPTIONS,
                "runs": queries.recent_runs(backend.wh, backend.fq),
                "active_run": ({"run_id": active.run_id, "clinic": active.clinic, "patients": active.patients}
                               if active else None)}

    @api.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    api.mount("/static", StaticFiles(directory=STATIC), name="static")
    return api


def main() -> None:
    import uvicorn

    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    uvicorn.run(create_app(Backend.from_env()), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
