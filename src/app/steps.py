"""Plain-English lines and pipeline phases for agent steps, shared by the live panel and the log."""
from __future__ import annotations

import json

PHASES = ("observe", "reason", "decide", "act", "measure")

_PHASE_OF = {
    **dict.fromkeys(["get_network_kpis", "compare_clinic_to_network", "get_dropoff_by_visit_number",
                     "get_cancellation_reasons", "get_provider_breakdown", "get_lead_response_stats",
                     "get_capacity_by_daypart"], "reason"),
    **dict.fromkeys(["record_diagnosis", "assign_specialist"], "decide"),
    **dict.fromkeys(["find_at_risk_patients", "get_patient_history", "find_open_slots", "queue_action",
                     "get_stale_leads", "find_reactivation_candidates", "get_intervention_performance"],
                    "act"),
}
WRITE_TOOLS = {"record_diagnosis", "assign_specialist", "queue_action"}

# Tool name -> (sentence using the tool's arguments, sentence when an argument is missing)
PHRASES = {
    "get_network_kpis": ("Read the network's KPIs and revenue at stake",
                         "Read the network's KPIs and revenue at stake"),
    "compare_clinic_to_network": ("Compared {clinic_id} with the network", "Compared the clinic with the network"),
    "get_dropoff_by_visit_number": ("Checked where {clinic_id} patients drop out", "Checked where patients drop out"),
    "get_cancellation_reasons": ("Read why {clinic_id} appointments get cancelled",
                                 "Read why appointments get cancelled"),
    "get_provider_breakdown": ("Broke {clinic_id} down by chiropractor", "Broke the clinic down by chiropractor"),
    "get_lead_response_stats": ("Checked how fast {clinic_id} answers leads", "Checked how fast leads get answered"),
    "get_capacity_by_daypart": ("Compared mornings and afternoons at {clinic_id}",
                                "Compared mornings and afternoons"),
    "record_diagnosis": ("Recorded the diagnosis for {location_id}", "Recorded the diagnosis"),
    "assign_specialist": ("Handed {location_id} to the {specialist} specialist", "Handed the clinic to a specialist"),
    "find_at_risk_patients": ("Found patients going quiet at {clinic_id}", "Found patients going quiet"),
    "get_patient_history": ("Read the visit history of {patient_id_in}", "Read a patient's visit history"),
    "find_open_slots": ("Looked for open slots at {clinic_id}", "Looked for open slots"),
    "queue_action": ("Drafted outreach for {target_id}: {intervention}", "Drafted outreach"),
    "get_stale_leads": ("Pulled open leads at {clinic_id}", "Pulled open leads"),
    "find_reactivation_candidates": ("Found lapsed patients at {clinic_id}", "Found lapsed patients"),
    "get_intervention_performance": ("Checked which outreach worked before", "Checked which outreach worked before"),
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
            clinic = suffix if suffix.startswith("LOC") else self._diagnosed
            if clinic and (clinic, specialist) not in self._handed:
                self._handed.add((clinic, specialist))
                self._open.append((clinic, specialist))
                out.append({"agent": "Director", "text": f"Handed {clinic} to the {specialist} specialist",
                            "write": True, "phase": "decide"})
        if name == "assign_specialist":
            clinic = args.get("location_id") or (step.get("arguments") or "").strip()
            done = next((k for k in reversed(self._open)
                         if k[0] == clinic and args.get("specialist") in (None, k[1])), None)
            if done:
                self._open.remove(done)
                return out + [{"agent": "Director", "text": f"The {done[1]} specialist finished with {done[0]}",
                               "write": False, "phase": None}]
        view = step_view(step)
        return out + [view] if view else out
