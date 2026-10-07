import threading

import pytest

from app.live import LiveRuns, RunInProgress, RunLog


def step_events(log):
    return [e for e in log.events if e["type"] == "step"]


def follow_to_the_end(log):
    seen = []
    for _ in range(50):
        events, finished = log.wait(len(seen), timeout=2)
        seen += events
        if finished:
            return seen
    raise AssertionError("run never finished")


def test_phases_only_move_forward():
    log = RunLog("r1", "LOC007", 4)
    for phase in ("observe", "reason", "observe", "reason"):
        log.phase(phase)
    assert [e["phase"] for e in log.events] == ["observe", "reason"]


def test_a_step_lights_its_phase_before_it_is_shown():
    log = RunLog("r1", "LOC007", 4)
    log.phase("observe")
    log.step({"agent": "director", "name": "record_diagnosis", "arguments": '{"location_id": "LOC007"}',
              "result_preview": "{}"})
    assert [e["type"] for e in log.events] == ["phase", "phase", "step"]
    assert log.events[1]["phase"] == "decide"
    assert [e["seq"] for e in log.events] == [0, 1, 2]


def test_act_progress_counts_patients_for_retention():
    log = RunLog("r1", "LOC007", 4)
    for agent in ("retention:PT1", "retention:PT1", "retention:PT2"):
        log.step({"agent": agent, "name": "get_patient_history", "arguments": "{}", "result_preview": "[]"})
    assert [e["progress"] for e in step_events(log)] == ["1 of 4 patients", "1 of 4 patients", "2 of 4 patients"]


def test_act_progress_counts_drafts_for_other_specialists():
    log = RunLog("r1", "LOC012", 4)
    log.step({"agent": "leads:LOC012", "name": "get_stale_leads", "arguments": "{}", "result_preview": "[]"})
    log.step({"agent": "leads:LOC012", "name": "queue_action",
              "arguments": '{"target_id": "L1", "intervention": "Follow-up SMS"}', "result_preview": '{"queued": "A1"}'})
    log.step({"agent": "leads:LOC012", "name": "queue_action",
              "arguments": '{"target_id": "L1", "intervention": "Follow-up SMS"}',
              "result_preview": '{"error": "already queued"}'})
    assert [e["progress"] for e in step_events(log)] == [None, "1 draft", "1 draft"]


def test_wait_returns_new_events_or_times_out():
    log = RunLog("r1", "LOC007", 4)
    log.phase("observe")
    events, finished = log.wait(after=0, timeout=0.01)
    assert [e["seq"] for e in events] == [0] and finished is False
    assert log.wait(after=1, timeout=0.01) == ([], False)


def test_wait_wakes_up_when_an_event_arrives():
    log = RunLog("r1", "LOC007", 4)
    threading.Timer(0.05, lambda: log.phase("reason")).start()
    events, _ = log.wait(after=0, timeout=2)
    assert events[0]["phase"] == "reason"


def test_a_run_ends_with_done_and_blocks_a_second_run_meanwhile():
    release = threading.Event()

    def runner(clinic, patients, run_id, log):
        log.step({"agent": "director", "name": "get_network_kpis", "arguments": "{}", "result_preview": "[]"})
        log.step({"agent": "retention:PT1", "name": "queue_action",
                  "arguments": '{"target_id": "PT1", "intervention": "Membership offer"}',
                  "result_preview": '{"queued": "A1"}'})
        release.wait(2)
        return {"status": "SUCCEEDED", "actions_queued": 9}

    live = LiveRuns(runner, new_id=lambda: "r1")
    log = live.start("LOC007", 4)
    assert live.active() is log
    with pytest.raises(RunInProgress) as busy:
        live.start("LOC012", 4)
    assert (busy.value.run_id, busy.value.clinic) == ("r1", "LOC007")
    release.set()
    events = follow_to_the_end(log)
    assert [e["type"] for e in events] == ["phase", "phase", "step", "phase", "step", "done"]
    done = events[-1]
    assert (done["clinic"], done["status"], done["drafts"]) == ("LOC007", "SUCCEEDED", 1)
    assert live.active() is None and live.get("r1") is log and live.get("nope") is None


def test_a_failed_run_ends_with_an_error_and_frees_the_slot():
    def runner(*_):
        raise RuntimeError("SQL failed: warehouse stopped")

    ids = iter(["r1", "r2"])
    live = LiveRuns(runner, new_id=lambda: next(ids))
    events = follow_to_the_end(live.start("LOC007", 4))
    assert events[-1] == {"type": "error", "message": "RuntimeError: SQL failed: warehouse stopped", "seq": 1}
    assert live.start("LOC007", 4).run_id == "r2"
