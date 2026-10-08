from app.steps import PHASES, Narrator, phase_of, phrase, step_view, who


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
    assert phrase("get_provider_breakdown", '{"clinic_id": "LOC007"}') == "Looked at each chiropractor at LOC007"
    assert (phrase("queue_action", '{"target_id": "PT1", "intervention": "Membership offer"}')
            == "Wrote a message for PT1: Membership offer")


def test_phrase_survives_missing_or_malformed_arguments():
    assert phrase("get_provider_breakdown", "{}") == "Looked at each chiropractor"
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
    assert view == {"agent": "Director", "text": "Wrote down what's wrong at LOC007", "write": True,
                    "phase": "decide"}
    assert step_view({"agent": "retention:PT1", "name": "final", "arguments": ""}) is None
    assert (step_view({"agent": "director", "name": "final", "arguments": ""})["text"]
            == "Wrote the summary for the executive team")


def test_rejected_writes_are_not_marked_as_writes():
    view = step_view({"agent": "retention:PT1", "name": "queue_action",
                      "arguments": '{"target_id": "PT1", "intervention": "Membership offer"}',
                      "result_preview": '{"error": "Slot already offered"}'})
    assert view["write"] is False
    assert view["text"] == "Wrote a message for PT1: Membership offer (rejected by a check)"


DIAGNOSE = {"agent": "director", "name": "record_diagnosis", "arguments": '{"location_id": "LOC007"}',
            "result_preview": "{}"}
PATIENT = {"agent": "retention:PT1", "name": "get_patient_history", "arguments": '{"patient_id_in": "PT1"}',
           "result_preview": "[]"}
ASSIGN = {"agent": "director", "name": "assign_specialist",
          "arguments": '{"location_id": "LOC007", "specialist": "retention"}', "result_preview": "{}"}


def lines(steps):
    narrator = Narrator()
    return [(v["agent"], v["text"], v["write"]) for step in steps for v in narrator.views(step)]


def test_the_hand_off_is_shown_when_the_specialist_starts():
    assert lines([DIAGNOSE, PATIENT, dict(PATIENT, agent="retention:PT2"), ASSIGN]) == [
        ("Director", "Wrote down what's wrong at LOC007", True),
        ("Director", "Handed LOC007 to the retention specialist", True),
        ("Retention", "Read the visit history of PT1", False),
        ("Retention", "Read the visit history of PT1", False),
        ("Director", "The retention specialist finished with LOC007", False)]


def test_hand_offs_for_clinic_named_specialists_and_code_assigned_ones():
    leads = {"agent": "leads:LOC012", "name": "get_stale_leads", "arguments": '{"clinic_id": "LOC012"}',
             "result_preview": "[]"}
    auto = {"agent": "director", "kind": "auto", "name": "assign_specialist", "arguments": "LOC012",
            "result_preview": "Assigned by code after the Director stopped."}
    assert lines([leads, auto]) == [
        ("Director", "Handed LOC012 to the leads specialist", True),
        ("Leads", "Found leads still waiting at LOC012", False),
        ("Director", "The leads specialist finished with LOC012", False)]


def test_a_hand_off_without_specialist_steps_reads_as_before():
    assert lines([DIAGNOSE, ASSIGN])[-1] == ("Director", "Handed LOC007 to the retention specialist", True)


def test_the_whole_network_is_handed_to_the_marketing_specialist():
    channels = {"agent": "marketing:NETWORK", "name": "get_marketing_channels", "arguments": "{}", "result_preview": "[]"}
    move = {"agent": "marketing:NETWORK", "name": "queue_budget_shift",
            "arguments": '{"from_channel": "Paid Search", "to_channel": "Referral Program", "amount": 600000}',
            "result_preview": '{"queued": "ACT-1"}'}
    finding = {"agent": "marketing:NETWORK", "name": "record_network_finding", "arguments": "{}", "result_preview": "{}"}
    done = {"agent": "director", "kind": "auto", "name": "assign_specialist",
            "arguments": '{"location_id": "NETWORK", "specialist": "marketing"}', "result_preview": "{}"}
    assert lines([DIAGNOSE, channels, move, finding, done]) == [
        ("Director", "Wrote down what's wrong at LOC007", True),
        ("Director", "Handed the whole network to the marketing specialist", True),
        ("Marketing", "Read what each marketing channel costs", False),
        ("Marketing", "Queued a budget move: Paid Search to Referral Program", True),
        ("Marketing", "Wrote down what's wrong across the network", True),
        ("Director", "The marketing specialist finished with the whole network", False)]
    assert phase_of("queue_budget_shift") == "act" and phase_of("record_network_finding") == "decide"


def test_a_network_specialist_that_failed_says_so():
    failed = {"agent": "director", "kind": "auto", "name": "assign_specialist",
              "arguments": '{"location_id": "NETWORK", "specialist": "loyalty"}',
              "result_preview": "Failed: RuntimeError: endpoint timed out"}
    assert lines([failed]) == [("Director", "Handed the whole network to the loyalty specialist (it stopped with an error)", False)]
    started = {"agent": "loyalty:NETWORK", "name": "get_loyalty_stats", "arguments": "{}", "result_preview": "[]"}
    assert lines([started, failed])[-1] == (
        "Director", "The loyalty specialist stopped with an error on the whole network", False)
