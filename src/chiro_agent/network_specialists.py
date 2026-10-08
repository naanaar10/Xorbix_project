"""Specialists that work on the whole network rather than one clinic: marketing (where the budget
goes) and loyalty (patients who just finished a care plan). The Manager hands the network to them
after its clinic reviews. As everywhere, tools compute the numbers; the agent decides and writes."""
from __future__ import annotations

import json

from chiro_agent.context import RunContext, action_row, now, personal_rules, queue_action_tool
from chiro_agent.loop import run_agent
from chiro_agent.tools import Tool

NETWORK = "NETWORK"  # location_id for findings and actions that cover every clinic
MAX_SHARE_MOVED = 0.25  # at most a quarter of a channel's yearly budget leaves it

PLAIN_WORDS = """Write so a 10-year-old could follow it: short, simple words and short sentences. Keep
business words like cost per new patient, lead conversion and care plan. Never use tool or column
names, or anything with an underscore. Only use numbers that tools returned."""

MARKETING_SYSTEM = f"""You are the Marketing Specialist for a network of 50 chiropractic clinics.
The network spends millions a year on marketing. Some channels win a new patient for much less
money than others. Your job: find budget that would win more new patients somewhere else.

Steps:
1. Call get_marketing_channels to see each channel's spend and cost per new patient.
2. Propose one to three budget moves with queue_budget_shift. Each call prices the move with the
   network's own numbers and queues it for the marketing manager to approve. A channel can lose at
   most a quarter of its budget, and a channel can at most double, so pick moves that fit.
   You can call price_budget_shift first to try a move without queuing it.
3. Call record_network_finding once: what is going wrong, two or three facts with numbers, and
   what the marketing manager should do.
4. Reply with one sentence summing up what you queued.

The message in each move is a short note to the marketing manager (under 320 characters).
{PLAIN_WORDS}"""


LOYALTY_INTERVENTIONS = ["Wellness plan offer", "Referral ask", "Wellness plan offer + referral ask"]
LOYALTY_SYSTEM = f"""You are the Loyalty Specialist for a network of 50 chiropractic clinics.
When a patient finishes a care plan they feel better and like the clinic. That is the best moment to
offer a Wellness plan (regular visits to stay well) and to ask them to bring a friend or family member.
The best clinics do this well; most do not.

Steps:
1. Call get_loyalty_stats to compare clinics with the best 10% (Wellness uptake and referral rate).
2. The user message lists patients who just finished a care plan at the clinics furthest behind.
   For EACH patient, call queue_action once and choose from their own details:
   - Wellness plan offer: patients who will likely need ongoing care, for example a long
     Corrective plan, many visits, older age bands, or a Package Plan they already like.
   - Referral ask: patients who already referred someone, or who finished a short plan quickly.
   - Wellness plan offer + referral ask: when both clearly fit.
   In each message use the patient's own facts: the plan they finished, how many visits they did and
   whether they have referred anyone before. No prices. A referral ask invites them to bring a
   friend or family member.
3. Call record_network_finding once: what is going wrong, two or three facts with numbers (name the
   best clinic), and what every clinic should do when a care plan ends.
4. Reply with one sentence summing up what you queued.
{PLAIN_WORDS}

{personal_rules()}"""


def money(x: float) -> str:
    return f"${x / 1e6:.2f}M" if abs(x) >= 999_500 else f"${x / 1e3:,.0f}K"


def budget_shift_tool(ctx: RunContext) -> Tool:
    """Queue a marketing budget move for approval, priced by the price_budget_shift UC function.
    Caps hold across the whole run: a channel loses at most a quarter of its budget and at most
    doubles."""
    moved_out: dict[str, float] = {}
    moved_in: dict[str, float] = {}
    queued: set[str] = set()

    def run(args: dict) -> dict:
        frm, to = args.get("from_channel"), args.get("to_channel")
        amount = float(args.get("amount") or 0)
        if frm == to:
            return {"error": "Pick two different channels."}
        if amount <= 0:
            return {"error": "amount must be more than $0 a year."}
        if f"{frm} to {to}" in queued:
            return {"error": f"A move from {frm} to {to} is already queued. Pick another pair."}
        rows = ctx.uc_tools.fetch("price_budget_shift", {"from_channel": frm, "to_channel": to, "amount": amount})
        if not rows:
            return {"error": f"Unknown channel. Use the names from get_marketing_channels."}
        p = rows[0]
        out_cap = MAX_SHARE_MOVED * p["from_spend"] - moved_out.get(frm, 0.0)
        in_cap = p["to_spend"] - moved_in.get(to, 0.0)
        if amount > out_cap + 0.5:
            return {"error": f"{frm} can only lose {money(max(0.0, out_cap))} more this run (a quarter of its budget)."}
        if amount > in_cap + 0.5:
            return {"error": f"{to} can only take {money(max(0.0, in_cap))} more this run (it can at most double)."}
        if p["extra_patients"] <= 0:
            return {"error": f"Moving money from {frm} to {to} would win fewer patients, not more."}
        row = action_row(ctx, location_id=NETWORK, specialist="marketing", target_type="channel",
                         target_id=f"{frm} to {to}", arm="agent", intervention="Budget shift",
                         signal=f"Move {money(amount)} a year", channel="Email",
                         message=(args.get("message") or "")[:600], rationale=(args.get("rationale") or "")[:600],
                         expected_value=p["yearly_revenue"])
        ctx.insert_actions([row])
        moved_out[frm] = moved_out.get(frm, 0.0) + amount
        moved_in[to] = moved_in.get(to, 0.0) + amount
        queued.add(row["target_id"])
        return {"queued": row["action_id"], "status": "Pending staff approval",
                "extra_new_patients": p["extra_patients"], "yearly_revenue": p["yearly_revenue"]}

    return Tool(
        name="queue_budget_shift",
        description="Queue one marketing budget move for the marketing manager to approve. Prices it first; "
                    "refuses moves that break the caps or win fewer patients.",
        parameters={"type": "object", "required": ["from_channel", "to_channel", "amount", "message", "rationale"],
                    "properties": {
                        "from_channel": {"type": "string", "description": "Channel to take money from"},
                        "to_channel": {"type": "string", "description": "Channel to give it to"},
                        "amount": {"type": "number", "description": "Dollars a year to move"},
                        "message": {"type": "string", "description": "Short note to the marketing manager (under 320 characters)"},
                        "rationale": {"type": "string", "description": "One short, plain sentence a 10-year-old could follow, with the numbers behind this move"},
                    }},
        run=run)


FINDING_REMINDER = ("You have not called record_network_finding yet. Call it once now with what is going wrong, "
                    "two or three facts and what to do. Then reply with one short sentence.")


def network_finding_tool(ctx: RunContext, problem_type: str, value: float | None = None,
                         recorded: list | None = None) -> Tool:
    """Save what a network specialist found. It is worth `value` a year when a tool worked that out,
    otherwise the yearly value of everything the specialist queued."""

    def run(args: dict) -> dict:
        worth = value if value is not None else sum(
            r["expected_value"] or 0 for r in ctx.queued_rows if r["specialist"] == problem_type)
        ctx.wh.insert(ctx.table("clinic_diagnoses"), [{
            "run_id": ctx.run_id, "location_id": NETWORK, "problem_type": problem_type,
            "root_cause": (args.get("root_cause") or "")[:1000], "evidence": (args.get("evidence") or "")[:2000],
            "revenue_at_stake": round(float(worth), 2), "specialist": problem_type,
            "recommended_fix": (args.get("recommended_fix") or "")[:1000], "created_at": now()}])
        if recorded is not None:
            recorded.append(problem_type)
        return {"recorded": NETWORK}

    return Tool(
        name="record_network_finding",
        description="Save your finding for the whole network: what is going wrong, the facts, and what to do. Call once.",
        parameters={"type": "object", "required": ["root_cause", "evidence", "recommended_fix"],
                    "properties": {
                        "root_cause": {"type": "string", "description": "One plain sentence: what is going wrong and why"},
                        "evidence": {"type": "string", "description": "Two or three short facts with numbers from tools, separated by semicolons"},
                        "recommended_fix": {"type": "string", "description": "What to do, in one or two sentences"}}},
        run=run)


def run_marketing(ctx: RunContext) -> dict:
    tools = ctx.uc_tools.subset(["get_marketing_channels", "price_budget_shift"])
    tools.add(budget_shift_tool(ctx))
    recorded: list = []
    tools.add(network_finding_tool(ctx, "marketing", recorded=recorded))
    result = run_agent(ctx.client, ctx.settings.llm_endpoint, f"marketing:{NETWORK}", MARKETING_SYSTEM,
                       "Review the network's marketing budget now.", tools, max_steps=14, on_step=ctx.add_step,
                       unfinished=lambda: None if recorded else FINDING_REMINDER)
    return {"specialist": "marketing", "summary": result.final_text[:500]}


def loyalty_targets(ctx: RunContext, clinics: int = 2, per_clinic: int = 4):
    """The clinics with the most to gain and their patients who just finished a care plan, plus what
    bringing every clinic up to the best 10% is worth a year."""
    stats = ctx.uc_tools.fetch("get_loyalty_stats", {})
    clinic_rows = [r for r in stats if str(r["location_id"]).startswith("LOC")]
    behind = sorted(clinic_rows, key=lambda r: -(r["yearly_value"] or 0))[:clinics]
    patients = [{**p, "location_id": c["location_id"], "city": c["city"],
                 "clinic_name": ctx.clinic_name(c["location_id"])}
                for c in behind
                for p in ctx.uc_tools.fetch("find_recent_finishers",
                                            {"clinic_id": c["location_id"], "max_patients": per_clinic})]
    return stats, behind, patients, sum(r["yearly_value"] or 0 for r in clinic_rows)


def run_loyalty(ctx: RunContext) -> dict:
    stats, behind, patients, value = loyalty_targets(ctx)
    targets = {p["patient_id"]: {"location_id": p["location_id"], "care_plan_id": p["care_plan_id"],
                                 "signal": p["plan_type"]} for p in patients}
    queue = queue_action_tool(ctx, location_id=NETWORK, specialist="loyalty", target_type="patient",
                              interventions=LOYALTY_INTERVENTIONS, targets=targets,
                              value_of=lambda info: 0.0)
    tools = ctx.uc_tools.subset(["get_loyalty_stats"])
    tools.add(queue)
    recorded: list = []
    tools.add(network_finding_tool(ctx, "loyalty", value=value, recorded=recorded))
    user = ("Clinics furthest behind: " + ", ".join(f"{c['city']} ({c['location_id']})" for c in behind)
            + "\nPatients who just finished a care plan there:\n" + json.dumps(patients, default=str))
    result = run_agent(ctx.client, ctx.settings.llm_endpoint, f"loyalty:{NETWORK}", LOYALTY_SYSTEM, user, tools,
                       max_steps=len(patients) + 8, on_step=ctx.add_step,
                       unfinished=lambda: None if recorded else FINDING_REMINDER)
    return {"specialist": "loyalty", "summary": result.final_text[:500]}


NETWORK_SPECIALISTS = {"marketing": run_marketing, "loyalty": run_loyalty}
