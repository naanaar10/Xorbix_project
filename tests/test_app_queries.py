import pytest

from app import queries
from fakes import FakeWarehouse

FQ = "cat.sch"


def kpi_row(**changes):
    row = {"location_id": "LOC007", "location_name": "Milwaukee North", "city": "Milwaukee", "state": "WI",
           "annual_revenue": 2.0e6, "total_revenue_at_stake": 468_000.0, "largest_lever": "retention",
           "plan_completion_rate": 0.34, "med_completion": 0.51, "at_risk_patients": 120, "med_at_risk": 60,
           "lead_conversion_rate": 0.29, "med_conversion": 0.29, "median_response_hours": 3.0,
           "med_response_hours": 3.1, "pm_utilization": 0.57, "med_pm_util": 0.76, "am_utilization": 0.8,
           "med_am_util": 0.8, "no_show_rate": 0.09, "med_no_show": 0.09}
    row.update(changes)
    return row


def diagnosis_row(run_id="r1", problem="retention", started="2026-10-07 15:38:08", trigger="scheduled"):
    return {"run_id": run_id, "problem_type": problem, "root_cause": "One chiropractor works mornings only.",
            "evidence": "13% completion", "recommended_fix": "Offer afternoon slots", "specialist": problem,
            "revenue_at_stake": 468_000.0, "started_at": started, "trigger": trigger, "status": "SUCCEEDED"}


def impact_rows(run_id, agent_patients, started="2026-10-07T15:38:08Z", trigger="scheduled"):
    return [{"run_id": run_id, "started_at": started, "trigger": trigger, "arm": arm, "patients": n,
             "patients_returned": n // 4, "return_rate": 0.25, "lift_vs_holdout": 0.1,
             "annualized_network_revenue": 8.3e6}
            for arm, n in (("holdout", 19), ("agent", agent_patients), ("generic", 31))]


def test_network_counts_flagged_clinics_and_builds_the_bridge():
    wh = FakeWarehouse({
        "network_clinics": [
            {"location_id": "LOC001", "city": "Des Moines", "annual_revenue": 2e6, "total_revenue_at_stake": 10_000.0, "largest_lever": "leads"},
            {"location_id": "LOC007", "city": "Milwaukee", "annual_revenue": 2e6, "total_revenue_at_stake": 468_000.0, "largest_lever": "retention"},
            {"location_id": "LOC012", "city": "Chicago", "annual_revenue": 2e6, "total_revenue_at_stake": 1_100_000.0, "largest_lever": "leads"}],
        "network_bridge": [{"leads_value": 30e6, "capacity_value": 8e6, "retention_value": -1.0}]})
    net = queries.network(wh, FQ)
    assert net["revenue"] == 6e6 and net["goal"] == 250e6 and net["clinic_count"] == 3
    assert net["flagged_count"] == 2 and net["at_stake_total"] == 1_568_000.0
    assert [c["flagged"] for c in net["clinics"]] == [False, True, True]
    assert [b["key"] for b in net["bridge"]] == ["leads", "capacity", "retention", "new_clinics"]
    assert net["bridge"][2]["value"] == 0.0
    assert net["bridge"][3] == {"key": "new_clinics", "value": 206e6, "label": "Open about 103 new clinics"}


def test_network_never_shows_a_negative_remainder():
    wh = FakeWarehouse({
        "network_clinics": [{"location_id": "LOC001", "city": "Des Moines", "annual_revenue": 2e6,
                             "total_revenue_at_stake": 0.0, "largest_lever": "leads"}],
        "network_bridge": [{"leads_value": 300e6, "capacity_value": 0.0, "retention_value": 0.0}]})
    assert queries.network(wh, FQ)["bridge"][3] == {"key": "new_clinics", "value": 0.0,
                                                    "label": "No new clinics needed"}


def test_clinic_story_without_a_diagnosis():
    wh = FakeWarehouse({"clinic_kpis": [kpi_row()]})
    story = queries.clinic_story(wh, FQ, "LOC007")
    assert story["diagnosis"] is None and story["run"] is None
    assert story["actions"] == [] and story["controls"] == {} and story["impact"] == []
    assert story["lever"] == "retention"
    assert [k["label"] for k in story["kpis"]] == ["Plan completion", "Patients going quiet"]
    assert story["kpis"][0] == {"label": "Plan completion", "value": 0.34, "median": 0.51, "unit": "pct",
                                "better": "higher"}
    assert story["clinic"]["flagged"] is True
    assert wh.called("clinic_actions") == []


def test_clinic_story_with_a_diagnosis():
    actions = ([{"action_id": "A1", "arm": "agent", "status": "Pending", "message": "Hi there", "target_type": "patient"},
                {"action_id": "A2", "arm": "agent", "status": "Approved", "message": "Hi", "target_type": "patient"}]
               + [{"action_id": f"H{i}", "arm": "holdout"} for i in range(3)]
               + [{"action_id": f"G{i}", "arm": "generic"} for i in range(2)])
    wh = FakeWarehouse({"clinic_kpis": [kpi_row()], "clinic_diagnosis": [diagnosis_row()],
                        "clinic_actions": actions, "clinic_impact": impact_rows("r1", 30)})
    story = queries.clinic_story(wh, FQ, "LOC007")
    assert story["run"] == {"run_id": "r1", "started_at": "2026-10-07T15:38:08Z", "trigger": "scheduled",
                            "status": "SUCCEEDED"}
    assert story["diagnosis"]["root_cause"] == "One chiropractor works mornings only."
    assert [a["action_id"] for a in story["actions"]] == ["A1", "A2"]
    assert story["controls"] == {"holdout": 3, "generic": 2}
    assert [a["arm"] for a in story["impact"]] == ["agent", "generic", "holdout"]
    assert story["impact_run"]["same_as_story"] is True and story["impact_run"]["agent_patients"] == 30
    assert wh.called("clinic_actions")[0]["params"] == {"run_id": "r1", "clinic_id": "LOC007"}


def test_a_run_too_small_to_measure_shows_the_latest_big_measurement():
    wh = FakeWarehouse({"clinic_kpis": [kpi_row()],
                        "clinic_diagnosis": [diagnosis_row("live", trigger="app")],
                        "clinic_impact": impact_rows("live", 4, "2026-10-08T20:00:00Z", "app")
                        + impact_rows("r1", 30)})
    story = queries.clinic_story(wh, FQ, "LOC007")
    assert story["impact_run"] == {"run_id": "r1", "started_at": "2026-10-07T15:38:08Z", "trigger": "scheduled",
                                   "agent_patients": 30, "same_as_story": False}
    assert story["impact"][0]["patients"] == 30


def test_a_small_run_is_shown_when_nothing_bigger_exists():
    wh = FakeWarehouse({"clinic_kpis": [kpi_row()], "clinic_diagnosis": [diagnosis_row("live", trigger="app")],
                        "clinic_impact": impact_rows("live", 4, "2026-10-08T20:00:00Z", "app")})
    story = queries.clinic_story(wh, FQ, "LOC007")
    assert story["impact_run"]["run_id"] == "live" and story["impact_run"]["same_as_story"] is True


def test_a_leads_clinic_has_leads_kpis_and_no_impact():
    wh = FakeWarehouse({"clinic_kpis": [kpi_row(location_id="LOC012", largest_lever="leads")],
                        "clinic_diagnosis": [diagnosis_row(problem="leads")],
                        "clinic_impact": impact_rows("r1", 30)})
    story = queries.clinic_story(wh, FQ, "LOC012")
    assert [k["label"] for k in story["kpis"]] == ["Lead conversion", "Hours to first reply"]
    assert story["impact"] == [] and story["impact_run"] is None


def test_clinic_story_pins_a_run_only_when_asked():
    wh = FakeWarehouse({"clinic_kpis": [kpi_row()]})
    queries.clinic_story(wh, FQ, "LOC007")
    queries.clinic_story(wh, FQ, "LOC007", run_id="r9")
    latest, pinned = wh.called("clinic_diagnosis")
    assert ":run_id" not in latest["sql"] and latest["params"] == {"clinic_id": "LOC007"}
    assert ":run_id" in pinned["sql"] and pinned["params"] == {"clinic_id": "LOC007", "run_id": "r9"}


def test_unknown_clinic_raises_key_error():
    with pytest.raises(KeyError):
        queries.clinic_story(FakeWarehouse(), FQ, "LOC999")


def test_set_action_validates_and_never_touches_control_rows():
    wh = FakeWarehouse()
    with pytest.raises(ValueError):
        queries.set_action(wh, FQ, "A1", "Deleted")
    with pytest.raises(ValueError):
        queries.set_action(wh, FQ, "A1", "Approved", "   ")
    with pytest.raises(ValueError):
        queries.set_action(wh, FQ, "A1", "Approved", "x" * 601)
    queries.set_action(wh, FQ, "A1", "Approved", "  Hi there, edited  ")
    call = wh.called("set_action")[0]
    assert "arm = 'agent'" in call["sql"] and "message = :message" in call["sql"]
    assert call["params"] == {"status": "Approved", "action_id": "A1", "message": "Hi there, edited"}


def test_set_action_without_a_message_leaves_the_message_alone():
    wh = FakeWarehouse()
    queries.set_action(wh, FQ, "A1", "Rejected")
    assert "message =" not in wh.called("set_action")[0]["sql"]


def test_approve_all_only_touches_pending_agent_rows():
    wh = FakeWarehouse()
    queries.approve_all(wh, FQ, "r1", "LOC007")
    call = wh.called("approve_all")[0]
    assert "status = 'Pending'" in call["sql"] and "arm = 'agent'" in call["sql"]
    assert call["params"] == {"run_id": "r1", "clinic_id": "LOC007"}


def test_utc_iso_marks_warehouse_timestamps_as_utc():
    assert queries.utc_iso("2026-10-07T15:38:08.593Z") == "2026-10-07T15:38:08.593Z"
    assert queries.utc_iso("2026-10-07 15:38:08") == "2026-10-07T15:38:08Z"
    assert queries.utc_iso("2026-10-07T15:38:08+00:00") == "2026-10-07T15:38:08+00:00"
    assert queries.utc_iso(None) is None


def test_recent_runs_and_steps():
    wh = FakeWarehouse({
        "recent_runs": [{"run_id": "r1", "started_at": "2026-10-07 15:38:08", "trigger": "scheduled",
                         "clinics_investigated": 3, "actions_queued": 77, "status": "SUCCEEDED"}],
        "run_steps": [{"agent": "director", "name": "get_network_kpis", "arguments": "{}", "result_preview": "[]"},
                      {"agent": "retention:PT1", "name": "final", "arguments": "", "result_preview": "done"}]})
    assert queries.recent_runs(wh, FQ)[0]["started_at"] == "2026-10-07T15:38:08Z"
    assert queries.run_steps(wh, FQ, "r1") == [{"agent": "Director", "text": "Read the network's KPIs and revenue at stake",
                                              "write": False, "phase": "reason"}]
