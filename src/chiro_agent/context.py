"""Shared state for one Growth Director run, plus the Python write tools every agent can use."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from chiro_agent.config import Settings
from chiro_agent.db import Warehouse
from chiro_agent.tools import Tool, ToolRegistry


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class RunContext:
    settings: Settings
    wh: Warehouse
    client: Any
    uc_tools: ToolRegistry
    run_id: str
    max_at_risk: int = 120          # retention: at-risk patients split into arms
    max_agent_patients: int = 20    # retention: how many agent-arm patients get a full LLM review
    max_followups: int = 10         # leads/capacity: actions per clinic
    steps: list[dict] = field(default_factory=list)
    diagnoses: dict[str, dict] = field(default_factory=dict)
    specialist_runs: dict[str, str] = field(default_factory=dict)
    offered_slots: set[str] = field(default_factory=set)
    actions_queued: int = 0

    def table(self, name: str) -> str:
        return f"{self.settings.fq}.{name}"

    def add_step(self, step: dict) -> None:
        self.steps.append(step)

    def insert_actions(self, rows: list[dict]) -> None:
        self.wh.insert(self.table("action_queue"), rows)
        self.actions_queued += sum(1 for r in rows if r["arm"] != "holdout")


def stable_fraction(*parts: str) -> float:
    """Deterministic pseudo-random number in [0, 1) from text, for reproducible arm assignment."""
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest[:12], 16) / 16**12


def action_row(ctx: RunContext, *, location_id: str, specialist: str, target_type: str,
               target_id: str, arm: str, intervention: str, care_plan_id: str | None = None,
               signal: str | None = None, channel: str | None = None, message: str | None = None,
               offered_slot: str | None = None, rationale: str | None = None,
               expected_value: float | None = None) -> dict:
    action_id = "ACT-" + hashlib.sha256(f"{ctx.run_id}|{target_id}|{specialist}".encode()).hexdigest()[:10]
    return {
        "action_id": action_id, "run_id": ctx.run_id, "location_id": location_id,
        "specialist": specialist, "target_type": target_type, "target_id": target_id,
        "care_plan_id": care_plan_id, "arm": arm, "signal": signal, "intervention": intervention,
        "channel": channel, "message": message, "offered_slot": offered_slot, "rationale": rationale,
        "expected_value": None if expected_value is None else round(float(expected_value), 2),
        "status": "Holdout" if arm == "holdout" else "Pending", "created_at": now(),
        "reviewed_at": None, "reviewer_note": None,
    }


def queue_action_tool(ctx: RunContext, *, location_id: str, specialist: str, target_type: str,
                      interventions: list[str], targets: dict[str, dict],
                      value_of: callable) -> Tool:
    """A write tool bound to one specialist's allowed interventions and known targets."""
    queued: set[str] = set()

    def run(args: dict) -> dict:
        target = args.get("target_id")
        if target not in targets:
            return {"error": f"Unknown target_id {target}. Allowed: {sorted(targets)[:20]}"}
        if target in queued:
            return {"error": f"An action for {target} is already queued in this run."}
        if args.get("intervention") not in interventions:
            return {"error": f"intervention must be one of {interventions}"}
        slot = (args.get("offered_slot") or "").strip() or None
        if slot and slot in ctx.offered_slots:
            return {"error": f"Slot {slot} was already offered to another patient. Pick a different slot."}
        info = targets[target]
        row = action_row(ctx, location_id=location_id, specialist=specialist, target_type=target_type,
                         target_id=target, arm="agent", intervention=args["intervention"],
                         care_plan_id=info.get("care_plan_id"), signal=info.get("signal"),
                         channel=args.get("channel"), message=(args.get("message") or "")[:600],
                         offered_slot=slot, rationale=(args.get("rationale") or "")[:600],
                         expected_value=value_of(info))
        ctx.insert_actions([row])
        queued.add(target)
        if slot:
            ctx.offered_slots.add(slot)
        return {"queued": row["action_id"], "target_id": target, "status": "Pending staff approval"}

    return Tool(
        name="queue_action",
        description="Queue one outreach action for staff approval. Call once per target.",
        parameters={"type": "object", "required": ["target_id", "intervention", "channel", "message", "rationale"],
                    "properties": {
                        "target_id": {"type": "string", "description": f"The {target_type} id"},
                        "intervention": {"type": "string", "enum": interventions},
                        "channel": {"type": "string", "enum": ["SMS", "Phone call", "Email"]},
                        "message": {"type": "string", "description": "Short, warm message to send (max 320 characters, no names, no medical claims)"},
                        "offered_slot": {"type": "string", "description": "Slot offered, exactly as 'YYYY-MM-DD HH:MM with PROVIDER_ID' (e.g. '2026-10-09 13:30 with PRV0043'), if any"},
                        "rationale": {"type": "string", "description": "One sentence citing the signals behind this choice"},
                    }},
        run=run)


def steps_to_rows(ctx: RunContext) -> list[dict]:
    return [{"run_id": ctx.run_id, "agent": s["agent"], "step": i + 1, "kind": s["kind"],
             "name": s["name"], "arguments": s.get("arguments", "")[:2000],
             "result_preview": s.get("result_preview", "")[:2000], "created_at": now()}
            for i, s in enumerate(ctx.steps)]


def parse_rows(text: str) -> list[dict]:
    data = json.loads(text)
    if isinstance(data, dict) and "rows" in data:
        return data["rows"]
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(data["error"])
    return data


def slot_label(row: dict) -> str:
    return f"{row['slot_date']} {row['slot_time']} with {row['provider_id']}"


def open_slots_tool(ctx: RunContext) -> Tool:
    """find_open_slots, minus slots already offered to someone else in this run."""
    base = ctx.uc_tools.tools["find_open_slots"]

    def run(args: dict) -> list[dict]:
        wanted = int(args.get("max_slots") or 8)
        rows = base.run({**args, "max_slots": wanted + len(ctx.offered_slots)})
        free = [dict(r, slot=slot_label(r)) for r in rows if slot_label(r) not in ctx.offered_slots]
        return free[:wanted]

    return Tool(base.name, base.description + " Slots already offered in this run are hidden.",
                base.parameters, run)
