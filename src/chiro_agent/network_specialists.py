"""Specialists that work on the whole network rather than one clinic: marketing (where the budget
goes) and loyalty (patients who just finished a care plan). The Director hands the network to them
after its clinic reviews. As everywhere, tools compute the numbers; the agent decides and writes."""
from __future__ import annotations

from chiro_agent.context import RunContext, action_row, now
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


def network_finding_tool(ctx: RunContext, problem_type: str) -> Tool:
    """Save what a network specialist found, worth the yearly value of everything it queued."""

    def run(args: dict) -> dict:
        value = sum(r["expected_value"] or 0 for r in ctx.queued_rows if r["specialist"] == problem_type)
        ctx.wh.insert(ctx.table("clinic_diagnoses"), [{
            "run_id": ctx.run_id, "location_id": NETWORK, "problem_type": problem_type,
            "root_cause": (args.get("root_cause") or "")[:1000], "evidence": (args.get("evidence") or "")[:2000],
            "revenue_at_stake": round(float(value), 2), "specialist": problem_type,
            "recommended_fix": (args.get("recommended_fix") or "")[:1000], "created_at": now()}])
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
    tools.add(network_finding_tool(ctx, "marketing"))
    result = run_agent(ctx.client, ctx.settings.llm_endpoint, f"marketing:{NETWORK}", MARKETING_SYSTEM,
                       "Review the network's marketing budget now.", tools, max_steps=12, on_step=ctx.add_step)
    return {"specialist": "marketing", "summary": result.final_text[:500]}


NETWORK_SPECIALISTS = {"marketing": run_marketing}
