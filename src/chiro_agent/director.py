"""The Growth Director: finds where the network is losing the most revenue, works out why,
and assigns the right specialist to act on it."""
from __future__ import annotations

import json
import uuid

import mlflow

from chiro_agent.context import RunContext, now, steps_to_rows
from chiro_agent.loop import run_agent
from chiro_agent.specialists import SPECIALISTS
from chiro_agent.tools import Tool

DIRECTOR_SYSTEM = """You are the Growth Director for a network of 50 chiropractic clinics doing about
$100M a year. The goal is $250M. Every run you find where revenue is leaking, prove why, and send
the right specialist to fix it.

How to work:
1. {start}
2. For EACH clinic you pick, find the root cause, not just the symptom. Use at least two drill-down
   tools (compare_clinic_to_network, get_dropoff_by_visit_number, get_cancellation_reasons,
   get_provider_breakdown, get_lead_response_stats, get_capacity_by_daypart). Dig until you can name
   the specific step, provider, time of day or process that is failing.
3. Call record_diagnosis for that clinic: problem_type (retention, leads or capacity), a specific
   one-sentence root cause, the evidence as numbers copied from tool results, revenue_at_stake (the
   clinic's total revenue at stake from get_network_kpis), and a recommended fix.
4. Call assign_specialist for that clinic with a short brief for the specialist.
Only use numbers that tools returned. Never invent data. When you compare a clinic, compare it with
the network's overall figure (the median or "all" row), not with a narrower slice. When every picked clinic is done, reply
with a three-sentence summary for the executive team.

Clinic managers read everything you write, so write it for them, not for an analyst:
- Plain English and short sentences. Never use tool or column names, or anything with an underscore.
- Percentages and whole numbers, never decimals: "41% of afternoon slots are booked", not "0.41".
- Compare with the typical clinic: "leads wait 37 hours for a first reply; the typical clinic
  replies in 3".
- Say "booked" rather than "utilization", and "the typical clinic" rather than "the median".
- Introduce a chiropractor as "one chiropractor (PRV0041)", never by the ID alone, and refer to them
  as "they".
- root_cause: one sentence saying what is going wrong and why.
- evidence: two or three short facts, each with this clinic's figure and the typical clinic's,
  separated by semicolons.
- recommended_fix: one or two sentences saying what clinic staff should do."""


def _director_tools(ctx: RunContext):
    tools = ctx.uc_tools.subset([
        "get_network_kpis", "compare_clinic_to_network", "get_dropoff_by_visit_number",
        "get_cancellation_reasons", "get_provider_breakdown", "get_lead_response_stats",
        "get_capacity_by_daypart"])

    def record_diagnosis(args: dict) -> dict:
        clinic = args.get("location_id")
        problem = args.get("problem_type")
        if problem not in SPECIALISTS:
            return {"error": f"problem_type must be one of {list(SPECIALISTS)}"}
        row = {"run_id": ctx.run_id, "location_id": clinic, "problem_type": problem,
               "root_cause": args.get("root_cause", "")[:1000], "evidence": args.get("evidence", "")[:2000],
               "revenue_at_stake": float(args.get("revenue_at_stake") or 0), "specialist": problem,
               "recommended_fix": args.get("recommended_fix", "")[:1000], "created_at": now()}
        ctx.wh.insert(ctx.table("clinic_diagnoses"), [row])
        ctx.diagnoses[clinic] = row
        return {"recorded": clinic, "next": "call assign_specialist for this clinic"}

    def assign_specialist(args: dict) -> dict:
        clinic, specialist = args.get("location_id"), args.get("specialist")
        if clinic not in ctx.diagnoses:
            return {"error": f"Call record_diagnosis for {clinic} before assigning a specialist."}
        if specialist not in SPECIALISTS:
            return {"error": f"specialist must be one of {list(SPECIALISTS)}"}
        if clinic in ctx.specialist_runs:
            return {"error": f"{clinic} already has the {ctx.specialist_runs[clinic]} specialist this run."}
        ctx.specialist_runs[clinic] = specialist
        return SPECIALISTS[specialist](ctx, clinic, args.get("brief", ""))

    tools.add(Tool("record_diagnosis", "Save the root-cause diagnosis for one clinic.",
                   {"type": "object",
                    "required": ["location_id", "problem_type", "root_cause", "evidence", "revenue_at_stake", "recommended_fix"],
                    "properties": {
                        "location_id": {"type": "string"},
                        "problem_type": {"type": "string", "enum": list(SPECIALISTS)},
                        "root_cause": {"type": "string", "description": "One plain-English sentence: what is going wrong and why"},
                        "evidence": {"type": "string", "description": "Two or three short facts from tool results, in percentages, each compared with the typical clinic"},
                        "revenue_at_stake": {"type": "number", "description": "Annual $ at stake from get_network_kpis"},
                        "recommended_fix": {"type": "string", "description": "What clinic staff should do, in one or two sentences"}}},
                   record_diagnosis))
    tools.add(Tool("assign_specialist",
                   "Hand a diagnosed clinic to a specialist agent, which reviews patients or leads and queues actions. Returns what it did.",
                   {"type": "object", "required": ["location_id", "specialist", "brief"],
                    "properties": {
                        "location_id": {"type": "string"},
                        "specialist": {"type": "string", "enum": list(SPECIALISTS)},
                        "brief": {"type": "string", "description": "What the specialist should focus on and why"}}},
                   assign_specialist))
    return tools


def new_run_id() -> str:
    return f"run-{now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"


def run_growth_director(ctx: RunContext, clinics_per_run: int = 3, only_clinic: str | None = None,
                        trigger: str = "scheduled") -> dict:
    started = now()
    if only_clinic:
        start = (f"Investigate clinic {only_clinic} only. Call get_network_kpis to see the network "
                 f"median and this clinic's revenue at stake.")
        task = f"Run the Growth Director for clinic {only_clinic}."
    else:
        start = (f"Call get_network_kpis and pick the {clinics_per_run} clinics with the most revenue "
                 f"at stake.")
        task = f"Run tonight's Growth Director review of the network ({clinics_per_run} clinics)."

    @mlflow.trace(name="growth_director_run", span_type="CHAIN")
    def traced(task_text: str) -> dict:
        tools = _director_tools(ctx)

        def unassigned() -> list[str]:
            return [c for c in ctx.diagnoses if c not in ctx.specialist_runs]

        def unfinished() -> str | None:
            left = unassigned()
            if left:
                return (f"You diagnosed {', '.join(left)} but did not call assign_specialist for it. "
                        "Call assign_specialist now, then give your summary.")
            return None

        result = run_agent(ctx.client, ctx.settings.llm_endpoint, "director",
                           DIRECTOR_SYSTEM.format(start=start), task_text, tools,
                           max_steps=40, on_step=ctx.add_step, unfinished=unfinished)
        for clinic in unassigned():  # last resort: never leave a diagnosis without an owner
            d = ctx.diagnoses[clinic]
            tools.call("assign_specialist", {"location_id": clinic, "specialist": d["problem_type"],
                                             "brief": d["recommended_fix"]})
            ctx.add_step({"agent": "director", "kind": "auto", "name": "assign_specialist",
                          "arguments": clinic, "result_preview": "Assigned by code after the Director stopped."})
        return {"summary": result.final_text, "stopped_early": result.stopped_early}

    status, summary, trace_id = "SUCCEEDED", "", None
    try:
        out = traced(task)
        summary = out["summary"]
        if out["stopped_early"]:
            status = "STOPPED_AT_STEP_LIMIT"
    except Exception as e:  # noqa: BLE001 - record failed runs too
        status, summary = "FAILED", f"{type(e).__name__}: {e}"[:1000]
        raise
    finally:
        trace_id = mlflow.get_last_active_trace_id()
        ctx.wh.insert(ctx.table("agent_steps"), steps_to_rows(ctx), batch=6)
        ctx.wh.insert(ctx.table("agent_runs"), [{
            "run_id": ctx.run_id, "started_at": started, "finished_at": now(),
            "model": ctx.settings.llm_endpoint, "trigger": trigger,
            "clinics_investigated": len(ctx.diagnoses), "actions_queued": ctx.actions_queued,
            "mlflow_experiment_id": ctx.settings.experiment_id, "mlflow_trace_id": trace_id,
            "status": status, "summary": summary[:4000]}])
    return {"run_id": ctx.run_id, "status": status, "diagnoses": list(ctx.diagnoses),
            "specialists": ctx.specialist_runs, "actions_queued": ctx.actions_queued,
            "summary": summary, "trace_id": trace_id}


def build_context(settings, w, run_id: str | None = None, **limits) -> RunContext:
    from chiro_agent.db import Warehouse
    from chiro_agent.tools import UC_TOOL_NAMES, load_uc_tools
    wh = Warehouse(w, settings.warehouse_id)
    return RunContext(settings=settings, wh=wh, client=w.serving_endpoints.get_open_ai_client(),
                      uc_tools=load_uc_tools(w, wh, settings.fq, UC_TOOL_NAMES),
                      run_id=run_id or new_run_id(), **limits)


def summarize_json(result: dict) -> str:
    return json.dumps(result, indent=2, default=str)
