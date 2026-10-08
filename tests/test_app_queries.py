import pytest

from app import explain, queries
from fakes import FakeWarehouse
from test_explain import BRIDGE, CHICAGO, IMPACT, MILWAUKEE

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
    assert [b["key"] for b in net["bridge"]] == ["leads", "capacity", "retention", "marketing", "membership",
                                                 "referrals", "new_clinics"]
    assert net["bridge"][2]["value"] == 0.0 and net["bridge"][3]["value"] == 0.0
    assert {k: v for k, v in net["bridge"][-1].items() if k != "rows"} == {
        "key": "new_clinics", "value": 206e6, "label": "Open about 103 new clinics"}


def test_network_never_shows_a_negative_remainder():
    wh = FakeWarehouse({
        "network_clinics": [{"location_id": "LOC001", "city": "Des Moines", "annual_revenue": 2e6,
                             "total_revenue_at_stake": 0.0, "largest_lever": "leads"}],
        "network_bridge": [{"leads_value": 300e6, "capacity_value": 0.0, "retention_value": 0.0}]})
    new_clinics = queries.network(wh, FQ)["bridge"][-1]
    assert (new_clinics["value"], new_clinics["label"]) == (0.0, "No new clinics needed")


def test_clinic_story_without_a_diagnosis():
    wh = FakeWarehouse({"clinic_kpis": [kpi_row()]})
    story = queries.clinic_story(wh, FQ, "LOC007")
    assert story["diagnosis"] is None and story["run"] is None
    assert story["actions"] == [] and story["controls"] == {} and story["impact"] == []
    assert story["lever"] == "retention"
    assert [k["label"] for k in story["kpis"]] == ["Plan completion", "Patients going quiet"]
    assert story["kpis"][0] == {"label": "Plan completion", "value": 0.34, "median": 0.51, "unit": "pct",
                                "better": "higher",
                                "meaning": "Out of every care plan that ended last year, how many the patient finished."}
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
    # Wellness and referral messages from the whole-network loyalty agent aren't part of this story.
    assert "specialist <> 'loyalty'" in wh.called("clinic_actions")[0]["sql"]


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
    assert queries.run_steps(wh, FQ, "r1") == [{"agent": "Manager", "text": "Read every clinic's numbers and the money each one loses",
                                              "write": False, "phase": "reason"}]


def test_the_latest_story_skips_failed_runs_unless_one_is_picked():
    wh = FakeWarehouse({"clinic_kpis": [kpi_row()]})
    queries.clinic_story(wh, FQ, "LOC007")
    queries.clinic_story(wh, FQ, "LOC007", run_id="r9")
    latest, pinned = wh.called("clinic_diagnosis")
    assert "r.status <> 'FAILED'" in latest["sql"]
    assert "FAILED" not in pinned["sql"]


def test_run_steps_show_the_hand_off_before_the_specialist_works():
    wh = FakeWarehouse({"run_steps": [
        {"agent": "director", "name": "record_diagnosis", "arguments": '{"location_id": "LOC007"}', "result_preview": "{}"},
        {"agent": "retention:PT1", "name": "get_patient_history", "arguments": '{"patient_id_in": "PT1"}', "result_preview": "[]"},
        {"agent": "director", "name": "assign_specialist",
         "arguments": '{"location_id": "LOC007", "specialist": "retention"}', "result_preview": "{}"}]})
    assert [s["text"] for s in queries.run_steps(wh, FQ, "r1")] == [
        "Wrote down what's wrong at LOC007", "Handed LOC007 to the retention specialist",
        "Read the visit history of PT1", "The retention specialist finished with LOC007"]


def clinic_row(location_id, city, at_stake, **changes):
    row = {"location_id": location_id, "city": city, "annual_revenue": 2e6, "total_revenue_at_stake": at_stake,
           "largest_lever": "retention", "plan_completion_rate": 0.5, "lead_conversion_rate": 0.3,
           "median_response_hours": 3.0, "no_show_rate": 0.09, "pm_utilization": 0.75, "at_risk_patients": 100,
           "med_completion": 0.51, "med_conversion": 0.29, "med_response_hours": 3.1, "med_no_show": 0.09,
           "med_pm_util": 0.76}
    row.update(changes)
    return row


def test_network_lists_every_kpi_and_the_network_medians():
    wh = FakeWarehouse({"network_clinics": [clinic_row("LOC001", "Des Moines", 0.0, at_risk_patients=90),
                                            clinic_row("LOC007", "Milwaukee", 468_000.0, plan_completion_rate=0.34,
                                                       at_risk_patients=169),
                                            clinic_row("LOC012", "Chicago", 1_100_000.0, at_risk_patients=118)]})
    net = queries.network(wh, FQ)
    assert net["clinics"][1] == {"id": "LOC007", "city": "Milwaukee", "at_stake": 468_000.0, "lever": "retention",
                                 "flagged": True, "revenue": 2e6, "completion": 0.34, "conversion": 0.3,
                                 "reply_hours": 3.0, "no_shows": 0.09, "afternoons": 0.75, "quiet": 169}
    assert net["medians"] == {"completion": 0.51, "conversion": 0.29, "reply_hours": 3.1, "no_shows": 0.09,
                              "afternoons": 0.76, "quiet": 118}


RUN = {"run_id": "r1", "started_at": "2026-10-08 07:32:52", "trigger": "scheduled", "status": "SUCCEEDED",
       "summary": "Three clinics leak $2.5M a year.", "clinics_investigated": 3}


def test_run_overview_defaults_to_the_latest_nightly_run():
    wh = FakeWarehouse({
        "run_pick": [RUN],
        "run_diagnoses": [{"location_id": "LOC012", "city": "Chicago", "problem_type": "leads", "root_cause": "Slow replies",
                           "evidence": "37 h", "recommended_fix": "Call within an hour", "specialist": "leads",
                           "revenue_at_stake": 1.1e6}],
        "run_actions": [{"action_id": "A1", "location_id": "LOC012", "city": "Chicago", "specialist": "leads",
                         "arm": "agent", "target_type": "lead", "target_id": "L1", "status": "Pending",
                         "message": "Hi there"},
                        {"action_id": "H1", "location_id": "LOC007", "city": "Milwaukee", "specialist": "retention",
                         "arm": "holdout"},
                        {"action_id": "G1", "location_id": "LOC007", "city": "Milwaukee", "specialist": "retention",
                         "arm": "generic"},
                        {"action_id": "G2", "location_id": "LOC007", "city": "Milwaukee", "specialist": "retention",
                         "arm": "generic"}],
        "run_impact": [{"arm": "holdout", "patients": 21, "patients_returned": 1, "return_rate": 0.048,
                        "recovered_revenue": 900.0, "lift_vs_holdout": 0.0, "annualized_network_revenue": 0.0},
                       {"arm": "agent", "patients": 30, "patients_returned": 9, "return_rate": 0.3,
                        "recovered_revenue": 9000.0, "lift_vs_holdout": 0.252, "annualized_network_revenue": 11.1e6}]})
    data = queries.run_overview(wh, FQ)
    pick = wh.called("run_pick")[0]
    assert "status <> 'FAILED'" in pick["sql"] and "trigger <> 'app'" in pick["sql"] and pick["params"] == {}
    assert data["run"] == dict(RUN, started_at="2026-10-08T07:32:52Z")
    assert data["diagnoses"][0]["city"] == "Chicago"
    assert [a["action_id"] for a in data["actions"]] == ["A1"]
    assert data["actions"][0]["city"] == "Chicago" and data["actions"][0]["location_id"] == "LOC012"
    assert data["controls"] == {"LOC007": {"holdout": 1, "generic": 2}}
    assert [a["arm"] for a in data["impact"]] == ["agent", "holdout"]
    assert data["impact"][0]["recovered_revenue"] == 9000.0
    assert all(c["params"] == {"run_id": "r1"} for c in wh.calls if c["name"] not in ("run_pick", "outcome_inputs"))


def test_run_overview_for_a_picked_run():
    wh = FakeWarehouse({"run_pick": [RUN]})
    queries.run_overview(wh, FQ, "r1")
    pick = wh.called("run_pick")[0]
    assert "run_id = :run_id" in pick["sql"] and pick["params"] == {"run_id": "r1"}


def test_run_overview_without_any_run():
    wh = FakeWarehouse()
    assert queries.run_overview(wh, FQ) == {"run": None, "diagnoses": [], "actions": [], "controls": {}, "impact": [],
                                            "impact_math": None}
    assert [c["name"] for c in wh.calls] == ["run_pick"]


def test_approve_all_for_a_whole_run():
    wh = FakeWarehouse()
    queries.approve_all(wh, FQ, "r1")
    call = wh.called("approve_all")[0]
    assert "location_id" not in call["sql"] and call["params"] == {"run_id": "r1"}
    assert "status = 'Pending'" in call["sql"] and "arm = 'agent'" in call["sql"]


def math_row(label, value, how=""):
    return {"label": label, "value": value, "how": how}


def test_network_explains_its_numbers():
    wh = FakeWarehouse({
        "network_clinics": [dict(MILWAUKEE, location_id="LOC007", city="Milwaukee", annual_revenue=2e6,
                                 largest_lever="retention"),
                            dict(CHICAGO, location_id="LOC012", city="Chicago", annual_revenue=2e6, largest_lever="leads")],
        "network_bridge": [BRIDGE]})
    net = queries.network(wh, FQ)
    assert net["at_stake_math"]["rows"] == [math_row("Chicago", "$1.14M", "slow lead replies"),
                                            math_row("Milwaukee", "$468K", "patients quit their care plan"),
                                            math_row("Total each year", "$1.60M", "$1.14M + $468K")]
    assert "$150K" in net["at_stake_math"]["note"]
    bridge = explain.bridge_math(BRIDGE, revenue=4e6, clinic_count=2, goal=250e6)
    assert [b["rows"] for b in net["bridge"]] == [bridge["leads"], bridge["capacity"], bridge["retention"],
                                                 bridge["marketing"], bridge["membership"], bridge["referrals"],
                                                 bridge["new_clinics"]]
    assert net["units"] == explain.unit_math(MILWAUKEE)
    assert net["inputs"] == BRIDGE  # the what-if planner recomputes the path from these


def test_clinic_story_explains_its_stake_and_its_results():
    k = kpi_row(**MILWAUKEE, network_dropouts=38024.0)
    impact = [dict(a, run_id="r1", started_at="2026-10-07T15:38:08Z", trigger="scheduled") for a in IMPACT]
    wh = FakeWarehouse({"clinic_kpis": [k], "clinic_diagnosis": [diagnosis_row()], "clinic_impact": impact})
    story = queries.clinic_story(wh, FQ, "LOC007")
    assert story["math"] == dict(explain.clinic_math(k), units=explain.unit_math(k))
    assert story["impact_math"] == explain.outcome_math(IMPACT, 38024.0, MILWAUKEE["avg_visit_revenue"])
    assert "network_dropouts" in wh.called("clinic_kpis")[0]["sql"]


def test_a_clinic_without_results_has_no_results_math():
    story = queries.clinic_story(FakeWarehouse({"clinic_kpis": [kpi_row(**CHICAGO)]}), FQ, "LOC007")
    assert story["impact_math"] is None and story["math"]["total"]["value"] == "$1.14M"


def test_run_overview_explains_each_diagnosis_and_the_results():
    wh = FakeWarehouse({
        "run_pick": [RUN],
        "run_diagnoses": [dict(MILWAUKEE, location_id="LOC007", city="Milwaukee", problem_type="retention",
                               root_cause="Plans stall", evidence="34% vs 51%", recommended_fix="Offer afternoons",
                               specialist="retention", revenue_at_stake=397_371.0)],
        "run_impact": IMPACT,
        "outcome_inputs": [{"annual_dropouts": 38024.0, "avg_visit_revenue": 110.87444698630249}]})
    data = queries.run_overview(wh, FQ)
    dx = data["diagnoses"][0]
    assert dx["at_stake"] == MILWAUKEE["total_revenue_at_stake"]
    assert dx["math"] == explain.clinic_math(MILWAUKEE)
    assert set(dx) == {"location_id", "city", "problem_type", "root_cause", "evidence", "recommended_fix",
                       "specialist", "at_stake", "math"}
    assert data["impact_math"] == explain.outcome_math(IMPACT, 38024.0, 110.87444698630249)


def test_whole_network_findings_and_moves_are_labelled_whole_network():
    wh = FakeWarehouse({
        "run_pick": [RUN],
        "run_diagnoses": [{"location_id": "NETWORK", "city": None, "problem_type": "marketing",
                           "root_cause": "Paid Search costs the most", "evidence": "$329 vs $68",
                           "recommended_fix": "Move money", "specialist": "marketing", "revenue_at_stake": 5.1e6}],
        "run_actions": [{"action_id": "M1", "location_id": "NETWORK", "city": None, "specialist": "marketing",
                         "arm": "agent", "target_type": "channel", "target_id": "Paid Search to Referral Program",
                         "intervention": "Budget shift", "status": "Pending", "message": "Move $600K"}]})
    data = queries.run_overview(wh, FQ)
    assert data["diagnoses"][0]["city"] == "Whole network" and data["diagnoses"][0]["at_stake"] == 5.1e6
    assert data["diagnoses"][0]["math"] is None
    assert data["actions"][0]["city"] == "Whole network"
