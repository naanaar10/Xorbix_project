"""Personal messages: every specialist that writes to people is told to use that person's own facts,
the clinic's name and friendly times, and never ID codes, age or how they pay."""
from chiro_agent import network_specialists, specialists
from chiro_agent.config import Settings
from chiro_agent.context import RunContext, friendly_time, open_slots_tool
from chiro_agent.tools import Tool, ToolRegistry
from fakes import FakeWarehouse

NAMES = [{"location_id": "LOC007", "location_name": "Milwaukee Spine & Wellness"},
         {"location_id": "LOC024", "location_name": "Cincinnati Spine & Wellness"}]


class Warehouse(FakeWarehouse):
    def insert(self, table, rows, batch=None):
        pass


def make_ctx(**tools):
    registry = ToolRegistry()
    for name in ["get_patient_history", "get_intervention_performance", "find_open_slots", "get_lead_response_stats",
                 "get_stale_leads", "get_capacity_by_daypart", "find_reactivation_candidates", "get_loyalty_stats",
                 "find_recent_finishers"]:
        registry.add(Tool(name, "", {}, tools.get(name, lambda args: [])))
    return RunContext(Settings("cat", "sch", "wh", "llm"), Warehouse({"clinic_names": NAMES}), None, registry, "run-1")


def test_slot_times_are_written_the_friendly_way():
    assert friendly_time("2026-10-08", "14:30") == "Thursday, Oct 8 at 2:30 PM"
    assert friendly_time("2026-10-09", "09:00") == "Friday, Oct 9 at 9:00 AM"
    assert friendly_time("2026-10-12", "12:00") == "Monday, Oct 12 at 12:00 PM"


def test_open_slots_carry_a_friendly_time_for_the_message():
    ctx = make_ctx(find_open_slots=lambda args: [
        {"slot_date": "2026-10-08", "slot_time": "14:30", "provider_id": "PRV0043", "daypart": "Afternoon"}])
    slot = open_slots_tool(ctx).run({"clinic_id": "LOC007"})[0]
    assert slot["slot"] == "2026-10-08 14:30 with PRV0043" and slot["when"] == "Thursday, Oct 8 at 2:30 PM"


def test_clinic_names_are_looked_up_once():
    ctx = make_ctx()
    assert ctx.clinic_name("LOC007") == "Milwaukee Spine & Wellness"
    assert ctx.clinic_name("LOC024") == "Cincinnati Spine & Wellness"
    assert ctx.clinic_name("LOC099") == "the clinic"
    assert len(ctx.wh.called("clinic_names")) == 1


def capture(monkeypatch, module):
    prompts = []
    monkeypatch.setattr(module, "run_agent", lambda client, endpoint, name, system, user, tools, **kw:
                        prompts.append((system, user, name, tools)) or type("R", (), {"final_text": "Done."})())
    return prompts


def test_every_specialist_that_writes_to_people_gets_the_personal_rules(monkeypatch):
    prompts = capture(monkeypatch, specialists)
    ctx = make_ctx()
    ctx.uc_tools.add(Tool("find_at_risk_patients", "", {}, lambda args: [
        {"patient_id": f"PT{i}", "care_plan_id": f"CP{i}", "last_cancellation_reason": None,
         "remaining_plan_value": 900.0} for i in range(10)]))
    for run in (specialists.run_retention, specialists.run_leads, specialists.run_capacity):
        run(ctx, "LOC007", "Patients quit after visit 3.")
    assert len(prompts) >= 3  # leads, capacity and at least one retention patient in the agent group
    for system, _, _, _ in prompts:
        assert "at least two facts" in system and "Start with \"Hi there, it's Milwaukee Spine & Wellness.\"" in system
        assert "Never write ID codes" in system and "how they pay" in system and "never make up a time" in system
        assert "{" not in system  # every placeholder was filled
    # Leads can offer a real first visit, so they never invent one.
    leads_tools = next(tools for _, _, name, tools in prompts if name.startswith("leads"))
    assert "find_open_slots" in leads_tools.tools


def test_loyalty_messages_name_each_patients_own_clinic(monkeypatch):
    prompts = capture(monkeypatch, network_specialists)
    stats = [{"location_id": "LOC024", "city": "Cincinnati", "yearly_value": 139_402.0}]
    ctx = make_ctx(get_loyalty_stats=lambda args: stats,
                   find_recent_finishers=lambda args: [{"patient_id": "PT9", "care_plan_id": "CP9",
                                                        "plan_type": "Corrective"}])
    network_specialists.run_loyalty(ctx)
    system, user, _, _ = prompts[0]
    assert "at least two facts" in system and "Start with \"Hi there, it's \" and the patient's clinic_name" in system
    assert '"clinic_name": "Cincinnati Spine & Wellness"' in user
