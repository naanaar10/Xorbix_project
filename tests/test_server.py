import threading

from fastapi.testclient import TestClient

from app.live import LiveRuns
from app.server import Backend, create_app
from fakes import FakeWarehouse

NETWORK = {
    "network_clinics": [{"location_id": "LOC007", "city": "Milwaukee", "annual_revenue": 2e6,
                         "total_revenue_at_stake": 468_000.0, "largest_lever": "retention"}],
    "network_bridge": [{"leads_value": 1e6, "capacity_value": 1e6, "retention_value": 1e6}]}


def make_client(answers=None, runner=None, wh=None):
    live = LiveRuns(runner or (lambda *a: {"status": "SUCCEEDED"}), new_id=lambda: "r1")
    backend = Backend(wh or FakeWarehouse(answers), "cat.sch", "databricks-gpt-oss-120b",
                      "https://example/ml/experiments/1/traces", live)
    return TestClient(create_app(backend), raise_server_exceptions=False), backend


def test_network_and_page():
    client, _ = make_client(NETWORK)
    body = client.get("/api/network").json()
    assert body["flagged_count"] == 1 and body["clinics"][0]["id"] == "LOC007"
    page = client.get("/")
    assert page.status_code == 200 and "<title>Growth Director</title>" in page.text


def test_unknown_clinic_is_404_with_an_error_message():
    client, _ = make_client({})
    for path in ("/api/clinics/LOC999", "/api/clinics/drop%20table"):
        response = client.get(path)
        assert response.status_code == 404 and "No clinic" in response.json()["error"]


def test_decisions_are_validated():
    client, backend = make_client({})
    bad = client.post("/api/actions/A1", json={"status": "Deleted"})
    assert bad.status_code == 400 and "status must be one of" in bad.json()["error"]
    assert client.post("/api/actions/A1", json={}).status_code == 400
    assert client.post("/api/actions/A1", json={"status": "Approved", "message": "Hi there"}).json() == {"ok": True}
    assert backend.wh.called("set_action")[0]["params"]["message"] == "Hi there"
    assert client.post("/api/actions/approve-all", json={"run_id": "r1", "location_id": "LOC007"}).json() == {"ok": True}
    assert backend.wh.called("approve_all")


def test_a_second_run_is_409_and_meta_reports_the_active_run():
    release = threading.Event()

    def runner(clinic, patients, run_id, log):
        release.wait(2)
        return {"status": "SUCCEEDED"}

    client, _ = make_client(NETWORK, runner)
    assert client.post("/api/runs", json={"clinic": "LOC007", "patients": 40}).json() == {"run_id": "r1"}
    busy = client.post("/api/runs", json={"clinic": "LOC007"})
    assert busy.status_code == 409
    assert busy.json() == {"error": "A run is already in progress.", "run_id": "r1", "clinic": "LOC007"}
    meta = client.get("/api/meta").json()
    assert meta["active_run"] == {"run_id": "r1", "clinic": "LOC007", "patients": 8}
    assert meta["model"] == "databricks-gpt-oss-120b"
    release.set()
    events = []
    for _ in range(20):
        events += client.get("/api/runs/r1/events", params={"after": len(events)}).json()["events"]
        if events and events[-1]["type"] == "done":
            break
    assert events[-1]["type"] == "done"
    assert client.get("/api/meta").json()["active_run"] is None


def test_bad_runs_and_unknown_run_events():
    client, _ = make_client(NETWORK)
    assert client.post("/api/runs", json={"clinic": "LOC999"}).status_code == 400
    missing = client.get("/api/runs/nope/events")
    assert missing.status_code == 404 and "Reload" in missing.json()["error"]


def test_server_errors_come_back_as_json():
    class Broken(FakeWarehouse):
        def query(self, sql, params=None):
            raise RuntimeError("SQL failed: warehouse is stopped")

    client, _ = make_client(wh=Broken())
    response = client.get("/api/network")
    assert response.status_code == 500 and "warehouse is stopped" in response.json()["error"]


def test_run_overview_meta_assumptions_and_run_wide_approval():
    client, backend = make_client({"run_pick": [{"run_id": "r1", "started_at": "2026-10-08 07:32:52",
                                                 "trigger": "scheduled", "status": "SUCCEEDED", "summary": "S",
                                                 "clinics_investigated": 3}]})
    assert client.get("/api/run").json()["run"]["run_id"] == "r1"
    assert client.get("/api/run", params={"run_id": "r1"}).status_code == 200
    assumptions = client.get("/api/meta").json()["assumptions"]
    assert len(assumptions["reasons"]) == 5 and len(assumptions["interventions"]) == 7
    assert len(assumptions["rows"]) == 5 and all(len(r) == 7 for r in assumptions["rows"])
    assert client.post("/api/actions/approve-all", json={"run_id": "r1"}).json() == {"ok": True}
    assert backend.wh.called("approve_all")[0]["params"] == {"run_id": "r1"}
