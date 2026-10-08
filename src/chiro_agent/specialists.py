"""Specialist agents. The Manager assigns one per diagnosed clinic.

Retention is the deep specialist: at-risk patients are randomized into holdout / generic reminder /
agent arms before any LLM sees them, and every agent-arm patient gets an individual review.
Leads and Capacity are lighter: one conversation that queues a short list of follow-ups.
"""
from __future__ import annotations

import json

from chiro_agent.context import (RunContext, action_row, open_slots_tool, queue_action_tool,
                                 stable_fraction)
from chiro_agent.loop import run_agent

RETENTION_INTERVENTIONS = ["Specific slot offer", "Provider call", "Membership offer",
                           "Progress check-in", "Transport or telehealth option"]
GENERIC_REMINDER = ("Hi there, we noticed it's been a while since your last visit. "
                    "Reply or call us to book your next appointment.")
HOLDOUT_SHARE, GENERIC_SHARE = 0.20, 0.20

RETENTION_SYSTEM = """You are the Retention Specialist for clinic {clinic}.
Manager's brief: {brief}

A patient on an active care plan has gone quiet: overdue for their next visit with nothing booked.
Choose the ONE outreach most likely to bring them back, based on why they probably stopped:
- Specific slot offer: a concrete open time. Best for scheduling conflicts. If their chiropractor
  does not work afternoons, offer an afternoon slot with another chiropractor (find_open_slots).
- Provider call: their chiropractor calls personally. Best for dissatisfaction or unclear reasons.
- Membership offer: monthly membership to lower per-visit cost. Best for cost/insurance concerns.
- Progress check-in: why finishing the plan matters even when pain eases, plus a maintenance plan.
  Best for patients who stopped after early visits because they feel better.
- Transport or telehealth option: ride credit or telehealth check-in. Best for transportation issues.

The Manager's brief describes the clinic as a whole. Each patient can have a different reason,
so decide from THIS patient's own signals, and do not default to the clinic-wide answer:
- last_cancellation_reason, when present, is the strongest signal.
- No cancellation reason, but their chiropractor does not work afternoons
  (provider_works_afternoons false): they most likely could not get a time that works. Offer an
  afternoon slot with another chiropractor.
- payment_type Self-Pay, or cost-related cancellations, point to cost.
- age_band 65+ with transportation cancellations points to transport.
- Stopping after 2-5 visits with no complaint and a chiropractor who works afternoons often means
  they feel better.

Steps: call get_patient_history first. Use find_open_slots when you offer a time, and
get_intervention_performance if you want evidence from past runs. Then call queue_action exactly
once. The message must be warm, under 320 characters, start with "Hi there", contain no names
and no medical claims. The rationale is one short sentence a 10-year-old could follow, naming
the signals you used (no column names)."""

LEADS_SYSTEM = """You are the Leads Specialist for clinic {clinic}.
Manager's brief: {brief}

Open leads are going cold because first responses are slow. Call get_stale_leads, then queue a
follow-up for up to {n} of them with queue_action, newest first:
- Speed-to-lead call: phone call within the hour, for New leads.
- Follow-up SMS: for leads already contacted once.
- Nurture email: for older leads.
Messages: warm, under 320 characters, start with "Hi there", no names, no medical claims.
Finish with one sentence recommending the process change that would stop leads going cold."""

CAPACITY_SYSTEM = """You are the Capacity Specialist for clinic {clinic}.
Manager's brief: {brief}

The clinic has empty capacity. Use get_capacity_by_daypart and find_open_slots to see where, then
find_reactivation_candidates to find lapsed loyal patients, and queue up to {n} actions with
queue_action:
- Off-peak slot offer: offer a specific open afternoon slot (include it in offered_slot).
- Wellness check-in: invite a lapsed patient back for a maintenance visit.
Messages: warm, under 320 characters, start with "Hi there", no names, no medical claims.
Finish with one sentence recommending the process change that would cut no-shows or fill
the empty dayparts."""


def run_retention(ctx: RunContext, clinic: str, brief: str) -> dict:
    at_risk = ctx.uc_tools.fetch("find_at_risk_patients", {"clinic_id": clinic, "max_patients": ctx.max_at_risk})
    by_id = {p["patient_id"]: p for p in at_risk}
    holdout, generic, agent = [], [], []
    for p in at_risk:
        r = stable_fraction(ctx.run_id, p["patient_id"])
        (holdout if r < HOLDOUT_SHARE else generic if r < HOLDOUT_SHARE + GENERIC_SHARE else agent).append(p)
    agent = sorted(agent, key=lambda p: stable_fraction("order", ctx.run_id, p["patient_id"]))
    agent = agent[:ctx.max_agent_patients]  # random subset, so the arm stays unbiased

    def control(p, arm):
        return action_row(ctx, location_id=clinic, specialist="retention", target_type="patient",
                          target_id=p["patient_id"], care_plan_id=p["care_plan_id"], arm=arm,
                          signal=p["last_cancellation_reason"],
                          intervention="None (holdout)" if arm == "holdout" else "Generic reminder",
                          channel=None if arm == "holdout" else "SMS",
                          message=None if arm == "holdout" else GENERIC_REMINDER,
                          expected_value=0 if arm == "holdout" else p["remaining_plan_value"] * 0.08)
    ctx.insert_actions([control(p, "holdout") for p in holdout] + [control(p, "generic") for p in generic])

    targets = {p["patient_id"]: {"care_plan_id": p["care_plan_id"], "signal": p["last_cancellation_reason"],
                                 "value": p["remaining_plan_value"]} for p in agent}
    queue = queue_action_tool(ctx, location_id=clinic, specialist="retention", target_type="patient",
                              interventions=RETENTION_INTERVENTIONS, targets=targets,
                              value_of=lambda info: info["value"] * 0.25)
    tools = ctx.uc_tools.subset(["get_patient_history", "get_intervention_performance"])
    tools.add(open_slots_tool(ctx))
    tools.add(queue)
    system = RETENTION_SYSTEM.format(clinic=clinic, brief=brief)
    for p in agent:
        run_agent(ctx.client, ctx.settings.llm_endpoint, f"retention:{p['patient_id']}", system,
                  "Patient to win back:\n" + json.dumps(by_id[p["patient_id"]]), tools,
                  max_steps=6, on_step=ctx.add_step, max_tokens=1200)
    return {"specialist": "retention", "clinic": clinic, "at_risk_patients": len(at_risk),
            "holdout": len(holdout), "generic_reminder": len(generic), "agent_reviewed": len(agent)}


def _single_conversation(ctx: RunContext, clinic: str, brief: str, specialist: str, system: str,
                         target_tool: str, target_args: dict, id_field: str, interventions: list[str],
                         tool_names: list[str]) -> dict:
    rows = ctx.uc_tools.fetch(target_tool, target_args)
    targets = {r[id_field]: {"value": r.get("lifetime_visit_count") or 1} for r in rows}
    if target_tool == "find_reactivation_candidates":
        value_of = lambda info: 110.0 * 4 * 0.2  # ~4 visits if they come back, 20% response
    else:
        value_of = lambda info: 1900.0 * 0.15     # new patient value x conversion uplift
    queue = queue_action_tool(ctx, location_id=clinic, specialist=specialist,
                              target_type="lead" if id_field == "lead_id" else "patient",
                              interventions=interventions, targets=targets, value_of=value_of)
    tools = ctx.uc_tools.subset([n for n in tool_names if n != "find_open_slots"])
    if "find_open_slots" in tool_names:
        tools.add(open_slots_tool(ctx))
    tools.add(queue)
    result = run_agent(ctx.client, ctx.settings.llm_endpoint, f"{specialist}:{clinic}",
                       system.format(clinic=clinic, brief=brief, n=ctx.max_followups),
                       f"Work on clinic {clinic} now.", tools, max_steps=ctx.max_followups + 6,
                       on_step=ctx.add_step)
    return {"specialist": specialist, "clinic": clinic, "candidates": len(rows),
            "process_fix": result.final_text[:500]}


def run_leads(ctx: RunContext, clinic: str, brief: str) -> dict:
    return _single_conversation(
        ctx, clinic, brief, "leads", LEADS_SYSTEM, "get_stale_leads",
        {"clinic_id": clinic, "max_leads": ctx.max_followups * 2}, "lead_id",
        ["Speed-to-lead call", "Follow-up SMS", "Nurture email"],
        ["get_lead_response_stats", "get_stale_leads"])


def run_capacity(ctx: RunContext, clinic: str, brief: str) -> dict:
    return _single_conversation(
        ctx, clinic, brief, "capacity", CAPACITY_SYSTEM, "find_reactivation_candidates",
        {"clinic_id": clinic, "max_patients": ctx.max_followups * 2}, "patient_id",
        ["Off-peak slot offer", "Wellness check-in"],
        ["get_capacity_by_daypart", "find_open_slots", "find_reactivation_candidates"])


SPECIALISTS = {"retention": run_retention, "leads": run_leads, "capacity": run_capacity}
