"""Plain-English lines and pipeline phases for agent steps, shared by the live panel and the log."""
from __future__ import annotations

import json

PHASES = ("observe", "reason", "decide", "act", "measure")

_PHASE_OF = {
    **dict.fromkeys(["get_network_kpis", "compare_clinic_to_network", "get_dropoff_by_visit_number",
                     "get_cancellation_reasons", "get_provider_breakdown", "get_lead_response_stats",
                     "get_capacity_by_daypart"], "reason"),
    **dict.fromkeys(["record_diagnosis", "assign_specialist", "record_network_finding"], "decide"),
    **dict.fromkeys(["find_at_risk_patients", "get_patient_history", "find_open_slots", "queue_action",
                     "get_stale_leads", "find_reactivation_candidates", "get_intervention_performance",
                     "get_marketing_channels", "price_budget_shift", "queue_budget_shift",
                     "get_loyalty_stats", "find_recent_finishers"],
                    "act"),
}
WRITE_TOOLS = {"record_diagnosis", "assign_specialist", "queue_action", "queue_budget_shift", "record_network_finding"}
NETWORK = "NETWORK"  # location_id of the whole-network specialists' work

# Tool name -> (sentence using the tool's arguments, sentence when an argument is missing)
PHRASES = {
    "get_network_kpis": ("Read every clinic's numbers and the money each one loses",
                         "Read every clinic's numbers and the money each one loses"),
    "compare_clinic_to_network": ("Compared {clinic_id} with the other clinics", "Compared the clinic with the other clinics"),
    "get_dropoff_by_visit_number": ("Checked where {clinic_id} patients drop out", "Checked where patients drop out"),
    "get_cancellation_reasons": ("Read why {clinic_id} appointments get cancelled",
                                 "Read why appointments get cancelled"),
    "get_provider_breakdown": ("Looked at each chiropractor at {clinic_id}", "Looked at each chiropractor"),
    "get_lead_response_stats": ("Checked how fast {clinic_id} answers leads", "Checked how fast leads get answered"),
    "get_capacity_by_daypart": ("Compared mornings and afternoons at {clinic_id}",
                                "Compared mornings and afternoons"),
    "record_diagnosis": ("Wrote down what's wrong at {location_id}", "Wrote down what's wrong"),
    "assign_specialist": ("Handed {location_id} to the {specialist} specialist", "Handed the clinic to a specialist"),
    "find_at_risk_patients": ("Found patients going quiet at {clinic_id}", "Found patients going quiet"),
    "get_patient_history": ("Read the visit history of {patient_id_in}", "Read a patient's visit history"),
    "find_open_slots": ("Looked for open slots at {clinic_id}", "Looked for open slots"),
    "queue_action": ("Wrote a message for {target_id}: {intervention}", "Wrote a message"),
    "get_stale_leads": ("Found leads still waiting at {clinic_id}", "Found leads still waiting"),
    "find_reactivation_candidates": ("Found patients who stopped coming to {clinic_id}", "Found patients who stopped coming"),
    "get_intervention_performance": ("Checked which messages worked before", "Checked which messages worked before"),
    "get_marketing_channels": ("Read what each marketing channel costs", "Read what each marketing channel costs"),
    "price_budget_shift": ("Priced moving money from {from_channel} to {to_channel}", "Priced a budget move"),
    "queue_budget_shift": ("Queued a budget move: {from_channel} to {to_channel}", "Queued a budget move"),
    "get_loyalty_stats": ("Compared every clinic's Wellness plans and referrals with the best clinics",
                          "Compared every clinic's Wellness plans and referrals with the best clinics"),
    "find_recent_finishers": ("Found patients who just finished a care plan at {clinic_id}",
                              "Found patients who just finished a care plan"),
    "record_network_finding": ("Wrote down what's wrong across the network", "Wrote down what's wrong across the network"),
    "reminder": ("Reminded to finish the hand-off", "Reminded to finish the hand-off"),
}


def phase_of(name: str) -> str | None:
    return _PHASE_OF.get(name)


def who(agent: str) -> str:
    return agent.split(":")[0].capitalize()


def _arguments(text: str | None) -> dict:
    try:
        value = json.loads(text or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def phrase(name: str, arguments: str | None) -> str:
    if name not in PHRASES:
        return name.replace("_", " ").capitalize()
    template, fallback = PHRASES[name]
    try:
        return template.format(**_arguments(arguments))
    except (KeyError, IndexError):
        return fallback


def step_view(step: dict) -> dict | None:
    """What the app shows for one agent step, or None when it isn't worth a line."""
    agent, name = step.get("agent") or "", step.get("name") or ""
    if name == "final":
        if not agent.startswith("director"):
            return None  # a specialist's sign-off repeats what its writes already showed
        text = "Wrote the summary for the executive team"
    else:
        text = phrase(name, step.get("arguments"))
    rejected = name in WRITE_TOOLS and '"error"' in (step.get("result_preview") or "")
    if rejected:
        text += " (rejected by a check)"
    return {"agent": who(agent), "text": text, "write": name in WRITE_TOOLS and not rejected,
            "phase": phase_of(name)}


def _place(clinic: str) -> str:
    return "the whole network" if clinic == NETWORK else clinic


class Narrator:
    """Lines for a run's steps in the order things happened. The loop records assign_specialist
    only after the specialist has finished (the specialist runs inside that tool call), so the
    hand-off line is shown when the specialist's first step arrives, and the late record reads
    as the specialist finishing."""

    def __init__(self):
        self._diagnosed: str | None = None          # clinic of the latest diagnosis
        self._handed: set[tuple[str, str]] = set()  # (clinic, specialist) hand-offs already shown
        self._open: list[tuple[str, str]] = []      # hand-offs whose specialist hasn't finished

    def views(self, step: dict) -> list[dict]:
        agent, name = step.get("agent") or "", step.get("name") or ""
        args = _arguments(step.get("arguments"))
        out = []
        if name == "record_diagnosis" and args.get("location_id"):
            self._diagnosed = args["location_id"]
        if agent and not agent.startswith("director"):
            specialist, _, suffix = agent.partition(":")
            clinic = suffix if suffix.startswith("LOC") or suffix == NETWORK else self._diagnosed
            if clinic and (clinic, specialist) not in self._handed:
                self._handed.add((clinic, specialist))
                self._open.append((clinic, specialist))
                out.append({"agent": "Director", "text": f"Handed {_place(clinic)} to the {specialist} specialist",
                            "write": True, "phase": "decide"})
        if name == "assign_specialist":
            clinic = args.get("location_id") or (step.get("arguments") or "").strip()
            failed = (step.get("result_preview") or "").startswith("Failed:")
            done = next((k for k in reversed(self._open)
                         if k[0] == clinic and args.get("specialist") in (None, k[1])), None)
            if done:
                self._open.remove(done)
                text = (f"The {done[1]} specialist stopped with an error on {_place(done[0])}" if failed
                        else f"The {done[1]} specialist finished with {_place(done[0])}")
                return out + [{"agent": "Director", "text": text, "write": False, "phase": None}]
            if clinic == NETWORK:  # handed over by code, but it never got to a first step
                text = f"Handed the whole network to the {args.get('specialist')} specialist"
                return out + [{"agent": "Director", "text": text + (" (it stopped with an error)" if failed else ""),
                               "write": not failed, "phase": "decide"}]
        view = step_view(step)
        return out + [view] if view else out
