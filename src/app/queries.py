"""Every read and write the app makes, through the SQL warehouse, returned as plain dicts.

`wh` is anything with `.query(sql, params) -> list[dict]`: chiro_agent.db.Warehouse in the app, a
fake in tests. Each statement starts with a /* name */ tag so the test fake can answer it."""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app import explain
from app.steps import Narrator

NETWORK = "NETWORK"     # location_id of the whole-network specialists' findings and moves
FLAG_ABOVE = 150_000   # dollars a year at stake before a clinic counts as out of alignment
GOAL = 250e6
STATUSES = ("Pending", "Approved", "Rejected")
MAX_MESSAGE = 600
MIN_MEASURED = 10      # agent-arm patients a run needs before its result is shown on its own
ARM_ORDER = ("agent", "generic", "holdout")
ACTION_FIELDS = ("action_id", "target_type", "target_id", "intervention", "channel", "message",
                 "offered_slot", "rationale", "status", "signal")
DIAGNOSIS_FIELDS = ("problem_type", "root_cause", "evidence", "recommended_fix", "specialist",
                    "revenue_at_stake")
IMPACT_FIELDS = ("arm", "patients", "patients_returned", "return_rate", "recovered_revenue", "lift_vs_holdout",
                 "annualized_network_revenue")

# Lever -> KPI bars: (label, clinic column, network median column, unit, which way is better)
KPIS = {
    "retention": [("Plan completion", "plan_completion_rate", "med_completion", "pct", "higher"),
                  ("Patients going quiet", "at_risk_patients", "med_at_risk", "count", "lower")],
    "leads": [("Lead conversion", "lead_conversion_rate", "med_conversion", "pct", "higher"),
              ("Hours to first reply", "median_response_hours", "med_response_hours", "hours", "lower")],
    "capacity": [("Afternoons booked", "pm_utilization", "med_pm_util", "pct", "higher"),
                 ("Mornings booked", "am_utilization", "med_am_util", "pct", "higher"),
                 ("No-shows", "no_show_rate", "med_no_show", "pct", "lower")],
}
# What each KPI measures, in plain words (src/sql/observe.sql computes them).
KPI_MEANING = {
    "plan_completion_rate": "Out of every care plan that ended last year, how many the patient finished.",
    "at_risk_patients": "Patients in the middle of a care plan who are late for their next visit and have "
                        "nothing booked.",
    "lead_conversion_rate": "Out of every new lead (someone who asked about coming in), how many became "
                            "patients. The last 30 days are left out because those people are still deciding.",
    "median_response_hours": "How long a new lead usually waits before the clinic answers.",
    "pm_utilization": "How full the afternoon schedule was last year. Each chiropractor has 10 slots every "
                      "weekday afternoon.",
    "am_utilization": "How full the morning schedule was last year. Each chiropractor has 10 slots every weekday "
                      "morning. It can go over 100% when extra patients are squeezed in.",
    "no_show_rate": "Out of every appointment last year, how many the patient missed without cancelling.",
}
# The all-clinics table: (key in the payload, clinic_kpis column, network median column)
TABLE_COLUMNS = (("revenue", "annual_revenue", None),
                 ("completion", "plan_completion_rate", "med_completion"),
                 ("conversion", "lead_conversion_rate", "med_conversion"),
                 ("reply_hours", "median_response_hours", "med_response_hours"),
                 ("no_shows", "no_show_rate", "med_no_show"),
                 ("afternoons", "pm_utilization", "med_pm_util"),
                 ("quiet", "at_risk_patients", None))
BRIDGE_LEVERS = (("leads_value", "leads", "Answer every lead within an hour"),
                 ("capacity_value", "capacity", "Fill afternoons to 85%"),
                 ("retention_value", "retention", "Help patients finish their care plan, like the best clinics"),
                 ("marketing_value", "marketing", "Move marketing money to the cheapest channel"))

BRIDGE_SQL = """/* network_bridge */
WITH ref AS (SELECT as_of FROM {fq}.network_metadata),
lead_rates AS (
  SELECT COUNT(*) * 365D / 335 AS leads_per_year,
         AVG(CAST(converted_flag AS DOUBLE)) AS conversion,
         AVG(CASE WHEN first_response_hours < 1 THEN CAST(converted_flag AS DOUBLE) END) AS conversion_within_hour
  FROM {fq}.leads CROSS JOIN ref
  WHERE created_date BETWEEN date_sub(ref.as_of, 365) AND date_sub(ref.as_of, 30)),
k AS (
  SELECT MAX(value_of_a_completion) AS completion_value, MAX(revenue_per_patient) AS revenue_per_patient,
         MAX(avg_visit_revenue) AS visit_revenue, SUM(closed_plans_per_year) AS closed_plans,
         MAX(med_completion) AS median_completion,
         percentile_approx(plan_completion_rate, 0.9) AS top_decile_completion,
         SUM(pm_capacity) AS pm_capacity, SUM(pm_capacity * pm_utilization) AS pm_booked
  FROM {fq}.clinic_kpis),
channels AS (
  SELECT c.channel, SUM(c.budget) AS spend, SUM(c.conversions) AS new_patients
  FROM {fq}.marketing_campaigns c CROSS JOIN ref
  WHERE c.start_date > date_sub(ref.as_of, 365) AND c.start_date <= ref.as_of
  GROUP BY c.channel),
mk AS (
  SELECT max_by(channel, spend / new_patients) AS costly_channel, max_by(spend, spend / new_patients) AS costly_spend,
         max_by(new_patients, spend / new_patients) AS costly_new_patients,
         min_by(channel, spend / new_patients) AS cheap_channel, min_by(spend, spend / new_patients) AS cheap_spend,
         min_by(new_patients, spend / new_patients) AS cheap_new_patients
  FROM channels),
moved AS (SELECT LEAST(0.25 * costly_spend, cheap_spend) AS marketing_moved FROM mk)
-- Each lever fixed across the whole network: every lead answered within an hour, afternoons
-- booked to 85%, plan completion raised from the median to the top-decile clinic's rate, and a
-- quarter of the costliest marketing channel's budget (at most what the cheapest spends) moved to
-- the cheapest, where it wins patients at half that channel's rate (price_budget_shift's rule).
SELECT *,
       GREATEST(0, leads_per_year * (conversion_within_hour - conversion) * revenue_per_patient) AS leads_value,
       GREATEST(0, pm_capacity * 0.85 - pm_booked) * visit_revenue AS capacity_value,
       GREATEST(0, closed_plans * (top_decile_completion - median_completion) * completion_value) AS retention_value,
       GREATEST(0, (marketing_moved / (2 * cheap_spend / cheap_new_patients)
                    - marketing_moved / (costly_spend / costly_new_patients)) * revenue_per_patient) AS marketing_value
FROM lead_rates CROSS JOIN k CROSS JOIN mk CROSS JOIN moved"""


def utc_iso(value: Any) -> str | None:
    """Warehouse timestamps are UTC; make sure the browser reads them that way."""
    if not value:
        return None
    text = str(value).replace(" ", "T", 1)
    if text.endswith("Z") or "+" in text[10:] or "-" in text[10:]:
        return text
    return text + "Z"


def network(wh: Any, fq: str) -> dict:
    with ThreadPoolExecutor(max_workers=2) as pool:
        clinics_job = pool.submit(wh.query, f"""/* network_clinics */
            SELECT * FROM {fq}.clinic_kpis ORDER BY location_id""")
        bridge_job = pool.submit(wh.query, BRIDGE_SQL.format(fq=fq))
        rows, bridge_rows = clinics_job.result(), bridge_job.result()
    clinics = [{"id": r["location_id"], "city": r["city"], "at_stake": r["total_revenue_at_stake"] or 0.0,
                "lever": r["largest_lever"], "flagged": (r["total_revenue_at_stake"] or 0) >= FLAG_ABOVE,
                **{key: r.get(column) for key, column, _ in TABLE_COLUMNS}}
               for r in rows]
    quiet = sorted(r.get("at_risk_patients") or 0 for r in rows)
    first = rows[0] if rows else {}
    medians = {key: first.get(median) for key, _, median in TABLE_COLUMNS if median}
    medians["quiet"] = quiet[(len(quiet) - 1) // 2] if quiet else None  # a real clinic's value, like percentile_approx
    revenue = sum(r["annual_revenue"] or 0 for r in rows)
    values = bridge_rows[0] if bridge_rows else {}
    bridge_math = explain.bridge_math(values, revenue, len(rows), GOAL)
    bridge = [{"key": key, "label": label, "value": max(0.0, values.get(column) or 0.0), "rows": bridge_math[key]}
              for column, key, label in BRIDGE_LEVERS]
    remainder = max(0.0, GOAL - revenue - sum(b["value"] for b in bridge))
    per_clinic = revenue / len(rows) if rows else 0.0
    new_clinics = math.ceil(remainder / per_clinic) if per_clinic else 0
    bridge.append({"key": "new_clinics", "value": remainder,
                   "label": f"Open about {new_clinics} new clinics" if new_clinics else "No new clinics needed",
                   "rows": bridge_math["new_clinics"]})
    flagged = sorted((c for c in clinics if c["flagged"]), key=lambda c: -c["at_stake"])
    at_stake_total = sum(c["at_stake"] for c in flagged)
    at_stake_math = {
        "rows": [explain.row(c["city"], explain.usd(c["at_stake"]), explain.TITLES.get(c["lever"], "").lower())
                 for c in flagged]
                + [explain.row("Total each year", explain.usd(at_stake_total),
                               " + ".join(explain.usd(c["at_stake"]) for c in flagged))],
        "note": (f"We flag a clinic when it loses more than {explain.usd(FLAG_ABOVE)} a year. Open a clinic to "
                 "see how its number was worked out.")}
    return {"revenue": revenue, "goal": GOAL, "clinic_count": len(clinics), "flagged_count": len(flagged),
            "at_stake_total": at_stake_total, "flag_above": FLAG_ABOVE, "at_stake_math": at_stake_math,
            "clinics": clinics, "medians": medians, "bridge": bridge, "units": explain.unit_math(first)}


def clinic_story(wh: Any, fq: str, clinic_id: str, run_id: str | None = None) -> dict:
    """One clinic's four-step story, from `run_id` or else the latest run that diagnosed it."""
    # A picked run is shown as it is; otherwise a failed run never replaces a good story.
    pinned = "AND d.run_id = :run_id" if run_id else "AND r.status <> 'FAILED'"
    dx_params = {"clinic_id": clinic_id, **({"run_id": run_id} if run_id else {})}
    with ThreadPoolExecutor(max_workers=3) as pool:
        kpi_job = pool.submit(wh.query, f"""/* clinic_kpis */
            SELECT k.*, (SELECT percentile_approx(at_risk_patients, 0.5) FROM {fq}.clinic_kpis) AS med_at_risk,
                   (SELECT SUM(closed_plans_per_year * (1 - plan_completion_rate)) FROM {fq}.clinic_kpis)
                     AS network_dropouts
            FROM {fq}.clinic_kpis k WHERE k.location_id = :clinic_id""", {"clinic_id": clinic_id})
        dx_job = pool.submit(wh.query, f"""/* clinic_diagnosis */
            SELECT d.run_id, d.problem_type, d.root_cause, d.evidence, d.recommended_fix, d.specialist,
                   d.revenue_at_stake, r.started_at, r.trigger, r.status
            FROM {fq}.clinic_diagnoses d JOIN {fq}.agent_runs r ON d.run_id = r.run_id
            WHERE d.location_id = :clinic_id {pinned}
            ORDER BY r.started_at DESC, d.created_at DESC LIMIT 1""", dx_params)
        impact_job = pool.submit(wh.query, f"""/* clinic_impact */
            SELECT s.run_id, r.started_at, r.trigger, s.arm, s.patients, s.patients_returned,
                   s.return_rate, s.recovered_revenue, s.lift_vs_holdout, s.annualized_network_revenue
            FROM {fq}.impact_summary s JOIN {fq}.agent_runs r ON s.run_id = r.run_id
            WHERE EXISTS (SELECT 1 FROM {fq}.clinic_diagnoses d WHERE d.run_id = s.run_id
                          AND d.location_id = :clinic_id AND d.problem_type = 'retention')
            ORDER BY r.started_at DESC""", {"clinic_id": clinic_id})
        kpi_rows, dx_rows = kpi_job.result(), dx_job.result()
        if not kpi_rows:
            raise KeyError(clinic_id)
        dx = dx_rows[0] if dx_rows else None
        action_rows = []
        if dx:
            action_rows = wh.query(f"""/* clinic_actions */
                SELECT action_id, arm, target_type, target_id, intervention, channel, message, offered_slot,
                       rationale, status, signal, expected_value
                FROM {fq}.action_queue WHERE run_id = :run_id AND location_id = :clinic_id
                ORDER BY expected_value DESC""", {"run_id": dx["run_id"], "clinic_id": clinic_id})
        impact_rows = impact_job.result()

    k = kpi_rows[0]
    lever = dx["problem_type"] if dx else k["largest_lever"]
    impact, impact_run = (_choose_impact(impact_rows, dx["run_id"]) if dx and lever == "retention"
                          else ([], None))
    controls: dict[str, int] = {}
    for r in action_rows:
        if r["arm"] != "agent":
            controls[r["arm"]] = controls.get(r["arm"], 0) + 1
    at_stake = k["total_revenue_at_stake"] or 0.0
    return {
        "clinic": {"id": k["location_id"], "name": k["location_name"], "city": k["city"], "state": k["state"],
                   "at_stake": at_stake, "lever": k["largest_lever"], "flagged": at_stake >= FLAG_ABOVE},
        "lever": lever,
        "kpis": [{"label": label, "value": k.get(column), "median": k.get(median), "unit": unit, "better": better,
                  "meaning": KPI_MEANING.get(column, "")}
                 for label, column, median, unit, better in KPIS.get(lever, KPIS["retention"])],
        "run": None if not dx else {"run_id": dx["run_id"], "started_at": utc_iso(dx["started_at"]),
                                    "trigger": dx["trigger"], "status": dx["status"]},
        "diagnosis": None if not dx else {f: dx[f] for f in DIAGNOSIS_FIELDS},
        "actions": [{f: r.get(f) for f in ACTION_FIELDS} for r in action_rows if r["arm"] == "agent"],
        "controls": controls,
        "impact": impact,
        "impact_run": impact_run,
        "impact_math": explain.outcome_math(impact, k.get("network_dropouts") or 0.0, k.get("avg_visit_revenue") or 0.0),
        "math": dict(explain.clinic_math(k), units=explain.unit_math(k)),
    }


def _arms(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: ARM_ORDER.index(r["arm"]) if r["arm"] in ARM_ORDER else len(ARM_ORDER))


def run_overview(wh: Any, fq: str, run_id: str | None = None) -> dict:
    """One whole run for the Diagnoses, Outreach and Results tabs: `run_id`, or else the latest
    nightly run that didn't fail (the latest successful live run if there is no nightly one)."""
    if run_id:
        where, params = "run_id = :run_id", {"run_id": run_id}
    else:
        where, params = "status <> 'FAILED'", {}
    runs = wh.query(f"""/* run_pick */
        SELECT run_id, started_at, trigger, status, summary, clinics_investigated FROM {fq}.agent_runs
        WHERE {where} ORDER BY CASE WHEN trigger <> 'app' THEN 0 ELSE 1 END, started_at DESC LIMIT 1""", params)
    if not runs:
        return {"run": None, "diagnoses": [], "actions": [], "controls": {}, "impact": [], "impact_math": None}
    run = dict(runs[0], started_at=utc_iso(runs[0]["started_at"]))
    by_run = {"run_id": run["run_id"]}
    with ThreadPoolExecutor(max_workers=4) as pool:
        dx_job = pool.submit(wh.query, f"""/* run_diagnoses */
            SELECT k.*, d.location_id, d.problem_type, d.root_cause, d.evidence, d.recommended_fix,
                   d.specialist, d.revenue_at_stake
            FROM {fq}.clinic_diagnoses d LEFT JOIN {fq}.clinic_kpis k ON d.location_id = k.location_id
            WHERE d.run_id = :run_id ORDER BY COALESCE(k.total_revenue_at_stake, d.revenue_at_stake) DESC""", by_run)
        inputs_job = pool.submit(wh.query, f"""/* outcome_inputs */
            SELECT SUM(closed_plans_per_year * (1 - plan_completion_rate)) AS annual_dropouts,
                   MAX(avg_visit_revenue) AS avg_visit_revenue
            FROM {fq}.clinic_kpis""")
        actions_job = pool.submit(wh.query, f"""/* run_actions */
            SELECT a.action_id, a.location_id, k.city, a.specialist, a.arm, a.target_type, a.target_id,
                   a.intervention, a.channel, a.message, a.offered_slot, a.rationale, a.status, a.signal
            FROM {fq}.action_queue a LEFT JOIN {fq}.clinic_kpis k ON a.location_id = k.location_id
            WHERE a.run_id = :run_id ORDER BY k.total_revenue_at_stake DESC, a.expected_value DESC""", by_run)
        impact_job = pool.submit(wh.query, f"""/* run_impact */
            SELECT arm, patients, patients_returned, return_rate, recovered_revenue, lift_vs_holdout,
                   annualized_network_revenue
            FROM {fq}.impact_summary WHERE run_id = :run_id""", by_run)
        dx_rows, action_rows, impact_rows = dx_job.result(), actions_job.result(), impact_job.result()
        inputs = (inputs_job.result() or [{}])[0]
    controls: dict[str, dict[str, int]] = {}
    for r in action_rows:
        if r["arm"] != "agent":
            arms = controls.setdefault(r["location_id"], {})
            arms[r["arm"]] = arms.get(r["arm"], 0) + 1
    # The clinic's own figure, the same one its page shows, with the math behind it.
    diagnoses = [{**{f: r.get(f) for f in ("location_id", "city", "problem_type", "root_cause", "evidence",
                                            "recommended_fix", "specialist")}, "city": _city(r),
                  "at_stake": r["total_revenue_at_stake"] if r.get("total_revenue_at_stake") is not None
                  else r.get("revenue_at_stake"),
                  "math": explain.clinic_math(r) if r.get("total_revenue_at_stake") is not None else None}
                 for r in dx_rows]
    impact = [{f: r.get(f) for f in IMPACT_FIELDS} for r in _arms(impact_rows)]
    return {
        "run": run,
        "diagnoses": diagnoses,
        "actions": [{"location_id": r["location_id"], "city": _city(r), "specialist": r.get("specialist"),
                     **{f: r.get(f) for f in ACTION_FIELDS}} for r in action_rows if r["arm"] == "agent"],
        "controls": controls,
        "impact": impact,
        "impact_math": explain.outcome_math(impact, inputs.get("annual_dropouts") or 0.0,
                                            inputs.get("avg_visit_revenue") or 0.0),
    }


def _city(row: dict) -> str | None:
    return "Whole network" if row.get("location_id") == NETWORK else row.get("city")


def _choose_impact(rows: list[dict], story_run: str) -> tuple[list[dict], dict | None]:
    """The story's own measurement when it is big enough; otherwise the latest run that is."""
    runs: dict[str, list[dict]] = {}
    for r in rows:  # newest run first
        runs.setdefault(r["run_id"], []).append(r)

    def agent_patients(run_rows: list[dict]) -> int:
        return next((r["patients"] for r in run_rows if r["arm"] == "agent"), 0)

    big = [run for run, run_rows in runs.items() if agent_patients(run_rows) >= MIN_MEASURED]
    if story_run in big:
        chosen = story_run
    elif big:
        chosen = big[0]
    elif story_run in runs:
        chosen = story_run
    else:
        return [], None
    run_rows = _arms(runs[chosen])
    first = run_rows[0]
    return ([{f: r.get(f) for f in IMPACT_FIELDS} for r in run_rows],
            {"run_id": chosen, "started_at": utc_iso(first["started_at"]), "trigger": first["trigger"],
             "agent_patients": agent_patients(run_rows), "same_as_story": chosen == story_run})


def set_action(wh: Any, fq: str, action_id: str, status: str, message: str | None = None) -> None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    params: dict[str, Any] = {"status": status, "action_id": action_id}
    set_message = ""
    if message is not None:
        message = message.strip()
        if not message or len(message) > MAX_MESSAGE:
            raise ValueError(f"message must be 1 to {MAX_MESSAGE} characters")
        params["message"] = message
        set_message = ", message = :message"
    wh.query(f"""/* set_action */
        UPDATE {fq}.action_queue SET status = :status{set_message}, reviewed_at = current_timestamp()
        WHERE action_id = :action_id AND arm = 'agent'""", params)


def approve_all(wh: Any, fq: str, run_id: str, clinic_id: str | None = None) -> None:
    """Approve every pending agent draft of a run, or only one clinic's."""
    params = {"run_id": run_id, **({"clinic_id": clinic_id} if clinic_id else {})}
    wh.query(f"""/* approve_all */
        UPDATE {fq}.action_queue SET status = 'Approved', reviewed_at = current_timestamp()
        WHERE run_id = :run_id {"AND location_id = :clinic_id" if clinic_id else ""}
          AND arm = 'agent' AND status = 'Pending'""", params)


def recent_runs(wh: Any, fq: str, limit: int = 15) -> list[dict]:
    rows = wh.query(f"""/* recent_runs */
        SELECT run_id, started_at, trigger, clinics_investigated, actions_queued, status
        FROM {fq}.agent_runs ORDER BY started_at DESC LIMIT {int(limit)}""")
    return [dict(r, started_at=utc_iso(r["started_at"])) for r in rows]


def run_steps(wh: Any, fq: str, run_id: str) -> list[dict]:
    rows = wh.query(f"""/* run_steps */
        SELECT agent, step, kind, name, arguments, result_preview FROM {fq}.agent_steps
        WHERE run_id = :run_id ORDER BY step""", {"run_id": run_id})
    narrator = Narrator()
    return [view for row in rows for view in narrator.views(row)]
