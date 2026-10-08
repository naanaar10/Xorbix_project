from app import explain

UNITS = {"avg_visit_revenue": 110.87444698630249, "revenue_per_patient": 1128.13060220889,
         "value_of_a_completion": 1911.5365056926555}
MEDIANS = {"med_completion": 0.5089903181189488, "med_conversion": 0.28953174797744546,
           "med_am_util": 0.8226053639846743, "med_pm_util": 0.7561029009304872,
           "med_no_show": 0.08240170832809948}
CHICAGO = {**UNITS, **MEDIANS, "plan_completion_rate": 0.5532953620829943, "closed_plans_per_year": 1229,
           "lead_conversion_rate": 0.15087313816127376, "leads_per_year": 8485.432835820895,
           "am_utilization": 0.8397509578544061, "am_capacity": 10440.0, "pm_utilization": 0.6888888888888889,
           "pm_capacity": 10440.0, "no_show_rate": 0.07834653878231859, "appointments_per_year": 19184,
           "retention_revenue_at_stake": 0.0, "leads_revenue_at_stake": 1135880.4803795202,
           "capacity_revenue_at_stake": 0.0, "total_revenue_at_stake": 1135880.4803795202}
ST_LOUIS = {**UNITS, **MEDIANS, "plan_completion_rate": 0.5489994869163674, "closed_plans_per_year": 1949,
            "lead_conversion_rate": 0.28352849336455893, "leads_per_year": 6978.582089552238,
            "am_utilization": 0.8028948488718604, "am_capacity": 23490.0, "pm_utilization": 0.4073222647935292,
            "pm_capacity": 23490.0, "no_show_rate": 0.1759611445959389, "appointments_per_year": 34178,
            "retention_revenue_at_stake": 0.0, "leads_revenue_at_stake": 0.0,
            "capacity_revenue_at_stake": 926685.4741565427, "total_revenue_at_stake": 926685.4741565427}
MILWAUKEE = {**UNITS, **MEDIANS, "plan_completion_rate": 0.3408637873754153, "closed_plans_per_year": 1505,
             "lead_conversion_rate": 0.2962674961119751, "leads_per_year": 5604.6567164179105,
             "am_utilization": 1.0183908045977013, "am_capacity": 10440.0, "pm_utilization": 0.5749680715197957,
             "pm_capacity": 7830.0, "no_show_rate": 0.08514862405558926, "appointments_per_year": 18133,
             "retention_revenue_at_stake": 397371.0284110195, "leads_revenue_at_stake": 0.0,
             "capacity_revenue_at_stake": 70436.95224972673, "total_revenue_at_stake": 467807.9806607462}


def row(label, value, how=""):
    return {"label": label, "value": value, "how": how}


def lever(math, key):
    return next(part for part in math["levers"] if part["key"] == key)


def test_number_formats():
    assert [explain.usd(x) for x in (1135880.48, 926685.47, 467807.98, 70436.95, 999_600, 29.7e6, 102.4e6, 450, 0)] \
        == ["$1.14M", "$927K", "$468K", "$70.4K", "$1.00M", "$29.7M", "$102M", "$450", "$0"]
    assert [explain.dollars(x) for x in (1128.13, 1911.54, 643.0)] == ["$1,128", "$1,912", "$643"]
    assert explain.cents(110.874) == "$110.87"
    assert explain.pct1(0.15087) == "15.1%" and explain.pts(0.11866) == "11.9 pts"
    assert explain.pts(0.02) == "2 pts" and explain.pts(0) == "0 pts" and explain.pts(0.1) == "10 pts"
    assert explain.count(8485.43) == "8,485"


def test_a_leads_gap_is_priced_step_by_step():
    leads = lever(explain.clinic_math(CHICAGO), "leads")
    assert leads["title"] == "Slow lead replies" and leads["value"] == 1135880.4803795202
    assert leads["rows"] == [
        row("Lead conversion gap", "11.9 pts", "29.0% typical clinic − 15.1% here − 2 pts normal variation"),
        row("Patients not won a year", "1,007", "11.9% × 8,485 leads a year"),
        row("A year at stake", "$1.14M", "1,007 × $1,128 per new patient")]


def test_a_problem_inside_normal_variation_is_worth_nothing():
    math = explain.clinic_math(CHICAGO)
    assert lever(math, "retention")["rows"] == [
        row("Plan completion gap", "0 pts", "55.3% here, better than the 50.9% typical clinic"),
        row("A year at stake", "$0")]
    assert lever(math, "capacity")["rows"][0] == row(
        "Mornings booked gap", "0 pts", "84.0% here, better than the 82.3% typical clinic")
    assert lever(math, "capacity")["rows"][2] == row(
        "No-show gap", "0 pts", "7.8% here, better than the 8.2% typical clinic")
    # Worse than typical, but by less than the band we treat as normal.
    assert lever(explain.clinic_math(ST_LOUIS), "capacity")["rows"][0] == row(
        "Mornings booked gap", "0 pts", "80.3% here vs 82.3% at the typical clinic: within the 10 pts of normal variation")


def test_empty_chairs_add_up_slots_and_no_shows():
    capacity = lever(explain.clinic_math(ST_LOUIS), "capacity")
    assert capacity["rows"][1:] == [
        row("Afternoons booked gap", "24.9 pts", "75.6% typical clinic − 40.7% here − 10 pts normal variation"),
        row("No-show gap", "7.4 pts", "17.6% here − 8.2% typical clinic − 2 pts normal variation"),
        row("Visits lost a year", "8,358", "24.9% × 23,490 afternoon slots + 7.4% × 34,178 appointments"),
        row("A year at stake", "$927K", "8,358 × $110.87 per visit")]
    assert capacity["note"] == ("Slots a year: 9 chiropractors × 10 half-hour slots a morning or afternoon "
                                "× 261 weekdays = 23,490.")


def test_the_total_adds_the_problems_biggest_first():
    math = explain.clinic_math(MILWAUKEE)
    assert [part["key"] for part in math["levers"]] == ["retention", "capacity", "leads"]
    assert lever(math, "retention")["rows"] == [
        row("Plan completion gap", "13.8 pts", "50.9% typical clinic − 34.1% here − 3 pts normal variation"),
        row("Plans not finished a year", "208", "13.8% × 1,505 plans that ended in the last year"),
        row("A year at stake", "$397K", "208 × $1,912 per finished plan")]
    assert lever(math, "capacity")["rows"][3:] == [
        row("Visits lost a year", "635", "8.1% × 7,830 afternoon slots"),
        row("A year at stake", "$70.4K", "635 × $110.87 per visit")]
    assert math["total"] == row("Total a year at stake", "$468K",
                                "$397K patients drop out + $70.4K empty chairs + $0 slow lead replies")


def test_every_lever_matches_the_figure_it_explains():
    for k in (CHICAGO, ST_LOUIS, MILWAUKEE):
        math = explain.clinic_math(k)
        for part in math["levers"]:
            assert part["value"] == k[f"{part['key']}_revenue_at_stake"]
            assert part["rows"][-1]["value"] == explain.usd(part["value"])
        assert math["total"]["value"] == explain.usd(k["total_revenue_at_stake"])


def test_unit_values_show_where_they_come_from():
    k = {**UNITS, "all_visit_revenue": 136_772_000.0, "all_visits": 1233568, "all_patients": 121237,
         "completer_revenue": 2554.538069916297, "dropper_revenue": 643.001564223642}
    assert explain.unit_math(k) == [
        row("Per new patient", "$1,128", "$137M of visit revenue ÷ 121,237 patients"),
        row("Per finished plan", "$1,912",
            "$2,555 average lifetime revenue of a patient who finished a plan − $643 for one who dropped out"),
        row("Per visit", "$110.87", "$137M of visit revenue ÷ 1,233,568 visits")]
    assert explain.unit_math(UNITS)[0] == row("Per new patient", "$1,128", "visit revenue ÷ patients")


BRIDGE = {"leads_per_year": 282195.1194029851, "conversion": 0.28789850232238484,
          "conversion_within_hour": 0.38118321420989315, "completion_value": 1911.5365056926555,
          "revenue_per_patient": 1128.13060220889, "visit_revenue": 110.87444698630249, "closed_plans": 78052,
          "median_completion": 0.5089903181189488, "top_decile_completion": 0.5520594965675057,
          "pm_capacity": 626400.0, "pm_booked": 462728.0, "leads_value": 29697463.218588624,
          "capacity_value": 7729279.448309119, "retention_value": 6425889.008176902}


def test_each_step_on_the_path_to_the_goal_shows_its_math():
    math = explain.bridge_math(BRIDGE, revenue=102.4e6, clinic_count=50, goal=250e6)
    assert math["leads"] == [
        row("Leads a year", "282,195", "every clinic, the last 11 months scaled to a year"),
        row("Conversion when a lead hears back within an hour", "38.1%"),
        row("Conversion today", "28.8%"),
        row("Extra patients a year", "26,324", "(38.1% − 28.8%) × 282,195 leads"),
        row("A year", "$29.7M", "26,324 × $1,128 per new patient")]
    assert math["capacity"] == [
        row("Afternoon slots a year", "626,400", "every chiropractor who works afternoons × 10 slots × 261 weekdays"),
        row("Booked today", "462,728", "73.9% of afternoon slots"),
        row("Booked at 85%", "532,440", "85% × 626,400"),
        row("Extra visits a year", "69,712", "532,440 − 462,728"),
        row("A year", "$7.73M", "69,712 × $110.87 per visit")]
    assert math["retention"] == [
        row("Plans that end a year", "78,052", "finished or dropped, every clinic"),
        row("Completion at the top 10% of clinics", "55.2%"),
        row("Completion at the typical clinic", "50.9%"),
        row("Extra plans finished a year", "3,362", "(55.2% − 50.9%) × 78,052 plans"),
        row("A year", "$6.43M", "3,362 × $1,912 per finished plan")]
    assert math["new_clinics"] == [
        row("Goal", "$250M"),
        row("Revenue today", "$102M", "visit revenue in the last 12 months, 50 clinics"),
        row("From the three fixes", "$43.9M", "$29.7M + $7.73M + $6.43M"),
        row("Still to find", "$104M", "$250M − $102M − $43.9M"),
        row("Revenue of a typical clinic", "$2.05M", "$102M ÷ 50 clinics"),
        row("New clinics", "51", "$104M ÷ $2.05M, rounded up")]


IMPACT = [
    {"arm": "agent", "patients": 30, "patients_returned": 9, "return_rate": 0.3, "recovered_revenue": 10710.49,
     "lift_vs_holdout": 0.2524, "annualized_network_revenue": 11057539.1},
    {"arm": "generic", "patients": 23, "patients_returned": 3, "return_rate": 0.1304, "recovered_revenue": 3570.16,
     "lift_vs_holdout": 0.0828, "annualized_network_revenue": 3628396.75},
    {"arm": "holdout", "patients": 21, "patients_returned": 1, "return_rate": 0.0476, "recovered_revenue": 698.51,
     "lift_vs_holdout": 0.0, "annualized_network_revenue": 0.0}]


def test_results_show_how_each_headline_number_was_worked_out():
    math = explain.outcome_math(IMPACT, annual_dropouts=38024.0, avg_visit_revenue=110.87444698630249)
    assert math["lift"] == [
        row("Came back after agent outreach", "30.0%", "9 of 30 patients"),
        row("Came back with no outreach", "4.8%", "1 of 21 patients, the holdout group"),
        row("More patients came back", "25.2 pts", "30.0% − 4.8%")]
    assert math["recovered"] == [
        row("Agent patients who came back", "9"),
        row("Visits left on their plans", "138", "the visits those 9 patients still had to go"),
        row("Visits we count", "96.6", "70% of 138: patients who come back don't all finish"),
        row("Recovered", "$10.7K", "96.6 × $110.87 per visit")]
    assert math["annualized"] == [
        row("More patients came back", "25.2 pts", "agent outreach vs no outreach, above"),
        row("Patients who drop out of a plan in a year", "38,024", "every clinic"),
        row("Extra patients back a year", "9,597", "25.2% × 38,024"),
        row("Value of a patient who comes back", "$1,152",
            "$15.0K recovered ÷ 13 patients who came back, in all groups"),
        row("A year across the network", "$11.1M", "9,597 × $1,152")]


def test_results_without_an_agent_arm_have_no_math():
    assert explain.outcome_math([], 38024.0, 110.87) is None
    assert explain.outcome_math(IMPACT[1:], 38024.0, 110.87) is None
