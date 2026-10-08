"""The whole-network specialists: their write tools price every move with a tool and enforce caps."""
from chiro_agent.config import Settings
from chiro_agent.context import RunContext
from chiro_agent.context import queue_action_tool
from chiro_agent.network_specialists import NETWORK, budget_shift_tool, loyalty_targets, network_finding_tool
from chiro_agent.tools import Tool, ToolRegistry

CHANNELS = {"Paid Search": (5_544_594.0, 16_846), "Referral Program": (645_118.0, 9_536), "SEO": (857_431.0, 6_480),
            "Direct Mail": (2_932_682.0, 10_149)}


class InsertOnly:
    def __init__(self):
        self.rows = {}

    def insert(self, table, rows, batch=None):
        self.rows.setdefault(table.split(".")[-1], []).extend(rows)


def price(args):
    """Same rule as price_budget_shift in src/sql/tools.sql."""
    (from_spend, from_new), (to_spend, to_new) = CHANNELS[args["from_channel"]], CHANNELS[args["to_channel"]]
    lost = args["amount"] / (from_spend / from_new)
    gained = args["amount"] / (2 * to_spend / to_new)
    return [{"from_spend": from_spend, "to_spend": to_spend, "patients_lost": lost, "patients_gained": gained,
             "extra_patients": gained - lost, "yearly_revenue": (gained - lost) * 1128.0}]


def make_ctx():
    registry = ToolRegistry()
    registry.add(Tool("get_marketing_channels", "", {}, lambda args: []))
    registry.add(Tool("price_budget_shift", "", {}, lambda args: price(args) if args["to_channel"] in CHANNELS
                      and args["from_channel"] in CHANNELS else []))
    return RunContext(Settings("cat", "sch", "wh", "llm"), InsertOnly(), None, registry, "run-1")


def shift(tool, frm="Paid Search", to="Referral Program", amount=400_000.0):
    return tool.run({"from_channel": frm, "to_channel": to, "amount": amount,
                     "message": "Move $400K from Paid Search to the Referral Program.",
                     "rationale": "Referrals cost $68 per new patient; Paid Search costs $329."})


def test_a_budget_shift_is_priced_by_the_tool_and_queued_for_approval():
    ctx = make_ctx()
    out = shift(budget_shift_tool(ctx))
    assert out["status"] == "Pending staff approval" and round(out["extra_new_patients"]) == 1741
    row = ctx.wh.rows["action_queue"][0]
    assert (row["location_id"], row["specialist"], row["target_type"], row["intervention"]) == \
        (NETWORK, "marketing", "channel", "Budget shift")
    assert row["target_id"] == "Paid Search to Referral Program" and row["signal"] == "Move $400K a year"
    assert row["expected_value"] == round(out["yearly_revenue"], 2) and row["status"] == "Pending"


def test_moves_are_capped_across_the_whole_run():
    tool = budget_shift_tool(make_ctx())
    # The cheaper channel can at most double: Referral Program spends $645K today.
    assert shift(tool, amount=400_000.0)["status"] == "Pending staff approval"
    refused = shift(tool, frm="Direct Mail", amount=300_000.0)
    assert "error" in refused and "Referral Program" in refused["error"]
    # At most a quarter of the source channel's budget can leave it: $1.39M for Paid Search.
    assert "error" in shift(tool, to="SEO", amount=1_000_000.0)
    assert shift(tool, to="SEO", amount=800_000.0)["status"] == "Pending staff approval"


def test_bad_moves_are_refused():
    tool = budget_shift_tool(make_ctx())
    assert "error" in shift(tool, to="Billboards")
    assert "error" in shift(tool, amount=0)
    assert "error" in shift(tool, frm="Referral Program", to="Referral Program")
    assert "error" in shift(tool, frm="Referral Program", to="Paid Search")  # loses patients


def test_the_network_finding_is_saved_with_the_value_of_what_was_queued():
    ctx = make_ctx()
    shift(budget_shift_tool(ctx))
    out = network_finding_tool(ctx, "marketing").run({
        "root_cause": "Most of the money goes to Paid Search, the most expensive way to win a patient.",
        "evidence": "Paid Search: $329 per new patient; Referral Program: $68", "recommended_fix": "Move money."})
    row = ctx.wh.rows["clinic_diagnoses"][0]
    assert out == {"recorded": NETWORK}
    assert (row["location_id"], row["problem_type"], row["specialist"]) == (NETWORK, "marketing", "marketing")
    assert row["revenue_at_stake"] == ctx.wh.rows["action_queue"][0]["expected_value"]


def test_the_director_hands_the_network_over_and_survives_a_failing_specialist(monkeypatch):
    from chiro_agent import director

    def broken(ctx):
        raise RuntimeError("endpoint timed out")

    monkeypatch.setattr(director, "NETWORK_SPECIALISTS",
                        {"marketing": lambda ctx: {"summary": "Queued two budget moves worth $5.1M a year."},
                         "loyalty": broken})
    ctx = make_ctx()
    lines = director.run_network_specialists(ctx)
    assert lines == "\n\n**Marketing (whole network)**: Queued two budget moves worth $5.1M a year."
    assert [(s["name"], s["arguments"]) for s in ctx.steps] == [
        ("assign_specialist", '{"location_id": "NETWORK", "specialist": "marketing"}'),
        ("assign_specialist", '{"location_id": "NETWORK", "specialist": "loyalty"}')]
    assert "endpoint timed out" in ctx.steps[1]["result_preview"]


STATS = [{"location_id": "TYPICAL", "city": "Typical clinic", "yearly_value": 0.0},
         {"location_id": "TOP_10_PERCENT", "city": "Best 10% of clinics", "yearly_value": 0.0},
         {"location_id": "LOC015", "city": "Springfield", "yearly_value": 133_642.0},
         {"location_id": "LOC024", "city": "Cincinnati", "yearly_value": 139_402.0},
         {"location_id": "LOC023", "city": "Columbus", "yearly_value": 117_907.0}]


def loyalty_ctx():
    ctx = make_ctx()
    ctx.uc_tools.add(Tool("get_loyalty_stats", "", {}, lambda args: STATS))
    ctx.uc_tools.add(Tool("find_recent_finishers", "", {}, lambda args: [
        {"patient_id": f"{args['clinic_id']}-P{i}", "care_plan_id": f"CP{i}", "plan_type": "Corrective"}
        for i in range(args["max_patients"])]))
    return ctx


def test_loyalty_works_on_the_clinics_furthest_behind():
    stats, behind, patients, value = loyalty_targets(loyalty_ctx(), clinics=2, per_clinic=3)
    assert [c["city"] for c in behind] == ["Cincinnati", "Springfield"]
    assert [p["patient_id"] for p in patients] == ["LOC024-P0", "LOC024-P1", "LOC024-P2",
                                                   "LOC015-P0", "LOC015-P1", "LOC015-P2"]
    assert patients[0]["location_id"] == "LOC024" and value == 390_951.0


def test_each_loyalty_message_is_filed_under_the_patients_own_clinic():
    ctx = loyalty_ctx()
    queue = queue_action_tool(ctx, location_id=NETWORK, specialist="loyalty", target_type="patient",
                              interventions=["Wellness plan offer", "Referral ask"],
                              targets={"PT1": {"location_id": "LOC024", "care_plan_id": "CP1", "signal": "Corrective"}},
                              value_of=lambda info: 300.0)
    out = queue.run({"target_id": "PT1", "intervention": "Wellness plan offer", "channel": "SMS",
                     "message": "Hi there, keep feeling good with our Wellness plan.", "rationale": "Long plan."})
    assert out["status"] == "Pending staff approval"
    assert ctx.wh.rows["action_queue"][0]["location_id"] == "LOC024"


def test_a_finding_can_carry_the_value_the_tools_worked_out():
    ctx = make_ctx()
    network_finding_tool(ctx, "loyalty", value=390_951.0).run({"root_cause": "x", "evidence": "y", "recommended_fix": "z"})
    assert ctx.wh.rows["clinic_diagnoses"][0]["revenue_at_stake"] == 390_951.0


def test_network_specialists_are_reminded_until_they_record_their_finding(monkeypatch):
    from chiro_agent import network_specialists as ns

    seen = {}

    def fake_run_agent(client, model, name, system, user, tools, **kwargs):
        unfinished = kwargs["unfinished"]
        seen[name] = [unfinished()]
        tools.call("record_network_finding", {"root_cause": "x", "evidence": "y", "recommended_fix": "z"})
        seen[name].append(unfinished())

        class Result:
            final_text = "Done."
        return Result()

    monkeypatch.setattr(ns, "run_agent", fake_run_agent)
    ns.run_marketing(make_ctx())
    ns.run_loyalty(loyalty_ctx())
    for name in ("marketing:NETWORK", "loyalty:NETWORK"):
        assert "record_network_finding" in seen[name][0] and seen[name][1] is None
