"""The outcome simulator must reward matching the intervention to the patient's real reason."""
from chiro_agent.measure import RETURN_PROBABILITY, return_probability, summarize


def test_best_intervention_matches_reason():
    best = {"Feeling better": "Progress check-in", "Scheduling conflict": "Specific slot offer",
            "Cost/insurance": "Membership offer", "Transportation": "Transport or telehealth option",
            "Dissatisfied": "Provider call"}
    interventions = ["Specific slot offer", "Provider call", "Membership offer", "Progress check-in",
                     "Transport or telehealth option", "Generic reminder", "None (holdout)"]
    for reason in RETURN_PROBABILITY:
        top = max(interventions, key=lambda i: return_probability(reason, i))
        assert top == best[reason]


def test_holdout_is_lowest_for_every_reason():
    for reason in RETURN_PROBABILITY:
        assert return_probability(reason, "None (holdout)") == min(RETURN_PROBABILITY[reason])


def test_summary_lift_and_projection():
    outcomes = ([{"arm": "agent", "returned": i < 4, "recovered_revenue": 1000.0 if i < 4 else 0.0} for i in range(10)]
                + [{"arm": "holdout", "returned": i < 1, "recovered_revenue": 1000.0 if i < 1 else 0.0} for i in range(10)])
    summary = {s["arm"]: s for s in summarize(outcomes, annual_dropouts=1000, run_id="r")}
    assert summary["agent"]["return_rate"] == 0.4
    assert summary["agent"]["lift_vs_holdout"] == 0.3
    assert summary["agent"]["annualized_network_revenue"] == 0.3 * 1000 * 1000.0
    assert summary["holdout"]["annualized_network_revenue"] == 0
