"""What the agent knew about each person it wrote to: short facts worked out from the data by SQL,
not by the AI, shown beside each message."""
from app.facts import action_facts, facts
from fakes import FakeWarehouse


def test_a_lead_shows_how_it_found_us_when_it_asked_and_whether_anyone_replied():
    assert facts({"target_type": "lead", "source": "Website Form", "lead_age_days": 3, "num_touchpoints": 0}) == \
        ["Found us: Website form", "Asked 3 days ago", "Not contacted yet"]
    assert facts({"target_type": "lead", "source": "Walk-In", "lead_age_days": 1, "num_touchpoints": 1}) == \
        ["Found us: Walk-in", "Asked yesterday", "Contacted once"]
    assert facts({"target_type": "lead", "source": "Referral", "lead_age_days": 0, "num_touchpoints": 4}) == \
        ["Found us: Referral", "Asked today", "Contacted 4 times"]


def test_a_patient_mid_plan_shows_their_progress_last_visit_and_usual_time():
    row = {"target_type": "patient", "plan_type": "Corrective", "plan_status": "Active", "visits_completed": 3,
           "prescribed_visits": 24, "days_since_visit": 26, "morning_share": 0.8, "lifetime_visit_count": 5,
           "referrals_made": 0}
    assert facts(row) == ["3 of 24 visits done", "Last visit 26 days ago", "Usually comes in the morning"]


def test_a_patient_who_finished_shows_the_plan_and_their_referrals():
    row = {"target_type": "patient", "plan_type": "Acute Relief", "plan_status": "Completed", "visits_completed": 12,
           "prescribed_visits": 12, "days_since_visit": 9, "morning_share": 0.3, "referrals_made": 1}
    assert facts(row) == ["Finished a 12-visit Acute Relief plan", "Last visit 9 days ago",
                          "Usually comes in the afternoon", "Has referred 1 person"]
    assert facts({**row, "referrals_made": 0})[-1] == "Hasn't referred anyone yet"
    assert facts({**row, "referrals_made": 3})[-1] == "Has referred 3 people"


def test_a_lapsed_patient_without_a_plan_shows_their_visits_in_all():
    row = {"target_type": "patient", "plan_type": None, "lifetime_visit_count": 38, "days_since_visit": 102,
           "morning_share": 0.5}
    assert facts(row) == ["38 visits in all", "Last visit 102 days ago", "Usually comes in the morning"]


def test_missing_values_are_left_out_and_budget_moves_have_no_facts():
    assert facts({"target_type": "patient", "days_since_visit": None, "morning_share": None}) == []
    assert facts({"target_type": "channel"}) == []


def test_facts_come_back_for_each_message_in_a_run_or_one_clinic():
    wh = FakeWarehouse({"action_facts": [
        {"action_id": "A1", "target_type": "lead", "source": "Referral", "lead_age_days": 2, "num_touchpoints": 0},
        {"action_id": "M1", "target_type": "channel"}]})
    assert action_facts(wh, "c.s", "r1") == {"A1": ["Found us: Referral", "Asked 2 days ago", "Not contacted yet"],
                                             "M1": []}
    call = wh.called("action_facts")[0]
    assert call["params"] == {"run_id": "r1"} and "arm = 'agent'" in call["sql"]
    action_facts(wh, "c.s", "r1", "LOC007")
    call = wh.called("action_facts")[1]
    assert call["params"] == {"run_id": "r1", "clinic_id": "LOC007"} and "location_id = :clinic_id" in call["sql"]
