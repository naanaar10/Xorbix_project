from app.steps import PHASES, phase_of, phrase, step_view, who


def test_phases_follow_the_tool_families():
    assert PHASES == ("observe", "reason", "decide", "act", "measure")
    assert phase_of("get_network_kpis") == "reason"
    assert phase_of("get_provider_breakdown") == "reason"
    assert phase_of("record_diagnosis") == "decide"
    assert phase_of("assign_specialist") == "decide"
    assert phase_of("get_patient_history") == "act"
    assert phase_of("queue_action") == "act"
    assert phase_of("final") is None


def test_phrase_fills_in_the_arguments():
    assert phrase("get_provider_breakdown", '{"clinic_id": "LOC007"}') == "Broke LOC007 down by chiropractor"
    assert (phrase("queue_action", '{"target_id": "PT1", "intervention": "Membership offer"}')
            == "Drafted outreach for PT1: Membership offer")


def test_phrase_survives_missing_or_malformed_arguments():
    assert phrase("get_provider_breakdown", "{}") == "Broke the clinic down by chiropractor"
    assert phrase("assign_specialist", "LOC007") == "Handed the clinic to a specialist"
    assert phrase("get_patient_history", "[1, 2]") == "Read a patient's visit history"
    assert phrase("some_new_tool", "") == "Some new tool"


def test_who_names_the_agent():
    assert who("director") == "Director"
    assert who("retention:PT0015829") == "Retention"
    assert who("leads:LOC012") == "Leads"


def test_step_view_marks_writes_and_hides_specialist_sign_offs():
    view = step_view({"agent": "director", "name": "record_diagnosis",
                      "arguments": '{"location_id": "LOC007"}', "result_preview": '{"recorded": "LOC007"}'})
    assert view == {"agent": "Director", "text": "Recorded the diagnosis for LOC007", "write": True,
                    "phase": "decide"}
    assert step_view({"agent": "retention:PT1", "name": "final", "arguments": ""}) is None
    assert (step_view({"agent": "director", "name": "final", "arguments": ""})["text"]
            == "Wrote the summary for the executive team")


def test_rejected_writes_are_not_marked_as_writes():
    view = step_view({"agent": "retention:PT1", "name": "queue_action",
                      "arguments": '{"target_id": "PT1", "intervention": "Membership offer"}',
                      "result_preview": '{"error": "Slot already offered"}'})
    assert view["write"] is False
    assert view["text"] == "Drafted outreach for PT1: Membership offer (rejected by a check)"
