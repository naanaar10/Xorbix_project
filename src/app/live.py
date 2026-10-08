"""Live Manager runs started from the app. Each run gets a background thread and an ordered event
log that the page long-polls. One run at a time, so two presenters can't start two at once."""
from __future__ import annotations

import threading
import time
from typing import Callable

from app.steps import PHASES, Narrator

MAX_RUN_SECONDS = 360  # a run still going after this is stopped: the model or warehouse hung


class RunLog:
    """Ordered events for one run: `phase` and `step`, then `done` or `error`. The run's thread
    writes; web requests read with wait()."""

    def __init__(self, run_id: str, clinic: str, patients: int):
        self.run_id, self.clinic, self.patients = run_id, clinic, patients
        self.started = time.monotonic()
        self.events: list[dict] = []
        self.finished = False
        self._phase = -1
        self._patients_seen: set[str] = set()
        self._drafts = 0
        self._narrator = Narrator()
        self._cond = threading.Condition()

    def _append(self, event: dict) -> None:
        event["seq"] = len(self.events)
        self.events.append(event)
        self._cond.notify_all()

    def _advance(self, phase: str) -> None:
        index = PHASES.index(phase)
        if index > self._phase:
            self._phase = index
            self._append({"type": "phase", "phase": phase})

    def phase(self, phase: str) -> None:
        with self._cond:
            if not self.finished:
                self._advance(phase)

    def step(self, step: dict) -> None:
        with self._cond:
            if self.finished:  # a run stopped for taking too long may still be talking
                return
            agent = step.get("agent") or ""
            if agent.startswith("retention:"):
                self._patients_seen.add(agent)
            views = self._narrator.views(step)
            if step.get("name") == "queue_action" and any(v["write"] for v in views):
                self._drafts += 1
            for view in views:
                if view["phase"]:
                    self._advance(view["phase"])
                self._append({"type": "step", **view, "progress": self._progress()})

    def _progress(self) -> str | None:
        if self._phase != PHASES.index("act"):
            return None
        if self._patients_seen:
            return f"{len(self._patients_seen)} of {self.patients} patients"
        if self._drafts:
            return f"{self._drafts} draft" + ("" if self._drafts == 1 else "s")
        return None

    def finish(self, result: dict) -> None:
        with self._cond:
            if self.finished:
                return
            self._append({"type": "done", "run_id": self.run_id, "clinic": self.clinic,
                          "status": result.get("status", "SUCCEEDED"), "drafts": self._drafts,
                          "seconds": round(time.monotonic() - self.started)})
            self.finished = True

    def fail(self, message: str) -> None:
        with self._cond:
            if self.finished:
                return
            self._append({"type": "error", "message": message[:500]})
            self.finished = True

    def wait(self, after: int, timeout: float) -> tuple[list[dict], bool]:
        """Events from seq `after` on, waiting up to `timeout` seconds for one to arrive."""
        after = max(0, after)
        with self._cond:
            self._cond.wait_for(lambda: len(self.events) > after or self.finished, timeout)
            return [dict(e) for e in self.events[after:]], self.finished


class RunInProgress(Exception):
    def __init__(self, log: RunLog):
        super().__init__(f"A run is already in progress for {log.clinic}: {log.run_id}")
        self.run_id, self.clinic = log.run_id, log.clinic


Runner = Callable[[str, int, str, RunLog], dict]


class LiveRuns:
    def __init__(self, runner: Runner, new_id: Callable[[], str], max_seconds: float = MAX_RUN_SECONDS):
        self._runner, self._new_id, self._max_seconds = runner, new_id, max_seconds
        self._logs: dict[str, RunLog] = {}
        self._active: RunLog | None = None
        self._lock = threading.Lock()

    def start(self, clinic: str, patients: int) -> RunLog:
        with self._lock:
            if self._active and not self._active.finished:
                raise RunInProgress(self._active)
            log = RunLog(self._new_id(), clinic, patients)
            self._logs[log.run_id] = log
            self._active = log
        # A hung run would keep the slot forever; stopping it frees Run the Manager again.
        watchdog = threading.Timer(self._max_seconds, log.fail,
                                   args=(f"The run was stopped after {self._max_seconds:g} seconds without finishing.",))
        watchdog.daemon = True
        watchdog.start()
        threading.Thread(target=self._run, args=(log, watchdog), name=f"live-{log.run_id}", daemon=True).start()
        return log

    def _run(self, log: RunLog, watchdog: threading.Timer) -> None:
        log.phase("observe")  # the KPI snapshot already exists; the Manager starts by reading it
        try:
            log.finish(self._runner(log.clinic, log.patients, log.run_id, log))
        except Exception as e:  # noqa: BLE001 - shown in the live panel
            log.fail(f"{type(e).__name__}: {e}")
        finally:
            watchdog.cancel()

    def get(self, run_id: str) -> RunLog | None:
        return self._logs.get(run_id)

    def active(self) -> RunLog | None:
        log = self._active
        return log if log and not log.finished else None


def director_runner(settings, w) -> Runner:
    """The real runner: the Manager agent on one clinic, then the outcome simulation."""

    def run(clinic: str, patients: int, run_id: str, log: RunLog) -> dict:
        import mlflow

        from chiro_agent.director import build_context, run_growth_director
        from chiro_agent.measure import measure_unmeasured_runs

        if settings.experiment_id:
            mlflow.set_tracking_uri("databricks")
            mlflow.set_experiment(experiment_id=settings.experiment_id)
        mlflow.openai.autolog()
        ctx = build_context(settings, w, run_id=run_id, max_at_risk=40, max_agent_patients=patients,
                            max_followups=4)

        def on_step(step: dict) -> None:
            ctx.steps.append(step)
            log.step(step)

        ctx.add_step = on_step
        result = run_growth_director(ctx, only_clinic=clinic, trigger="app")
        log.phase("measure")
        measure_unmeasured_runs(ctx.wh, settings.fq)
        return result

    return run
