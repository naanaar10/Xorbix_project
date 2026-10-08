"""What the agent knew about each person it wrote to: a few short facts worked out from the data by
SQL (not by the AI), shown beside each message so staff can check it says the right things."""
from __future__ import annotations

from typing import Any

FACTS_SQL = """/* action_facts */
    WITH a AS (
      SELECT action_id, target_type, target_id, care_plan_id FROM {fq}.action_queue
      WHERE run_id = :run_id AND arm = 'agent' {clinic_filter}),
    ids AS (SELECT DISTINCT target_id AS patient_id FROM a WHERE target_type = 'patient'),
    last_visit AS (
      SELECT v.patient_id, MAX(v.visit_date) AS last_visit
      FROM {fq}.visits v JOIN ids ON v.patient_id = ids.patient_id GROUP BY v.patient_id),
    usual AS (
      SELECT ap.patient_id, AVG(CASE WHEN ap.appointment_time < '13:00' THEN 1D ELSE 0D END) AS morning_share
      FROM {fq}.appointments ap JOIN ids ON ap.patient_id = ids.patient_id
      WHERE ap.status = 'Completed' GROUP BY ap.patient_id),
    referred AS (
      SELECT r.referring_patient_id AS patient_id, COUNT(*) AS n
      FROM {fq}.referrals r JOIN ids ON r.referring_patient_id = ids.patient_id GROUP BY r.referring_patient_id)
    SELECT a.action_id, a.target_type, l.source, datediff(m.as_of, l.created_date) AS lead_age_days,
           l.num_touchpoints, cp.plan_type, cp.status AS plan_status, cp.visits_completed, cp.prescribed_visits,
           p.lifetime_visit_count, datediff(m.as_of, lv.last_visit) AS days_since_visit, u.morning_share,
           COALESCE(rf.n, 0) AS referrals_made
    FROM a CROSS JOIN {fq}.network_metadata m
    LEFT JOIN {fq}.leads l ON a.target_type = 'lead' AND l.lead_id = a.target_id
    LEFT JOIN {fq}.care_plans cp ON cp.care_plan_id = a.care_plan_id
    LEFT JOIN {fq}.patients p ON a.target_type = 'patient' AND p.patient_id = a.target_id
    LEFT JOIN last_visit lv ON lv.patient_id = a.target_id
    LEFT JOIN usual u ON u.patient_id = a.target_id
    LEFT JOIN referred rf ON rf.patient_id = a.target_id"""


def _ago(days: int) -> str:
    return "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"


def _lead(r: dict) -> list[str]:
    out = []
    if r.get("source"):
        out.append(f"Found us: {r['source'][:1]}{r['source'][1:].lower()}")
    if r.get("lead_age_days") is not None:
        out.append(f"Asked {_ago(int(r['lead_age_days']))}")
    n = r.get("num_touchpoints")
    if n is not None:
        n = int(n)
        out.append("Not contacted yet" if n == 0 else "Contacted once" if n == 1 else f"Contacted {n} times")
    return out


def _patient(r: dict) -> list[str]:
    out = []
    finished = r.get("plan_status") == "Completed"
    if r.get("plan_type") and r.get("prescribed_visits"):
        out.append(f"Finished a {int(r['visits_completed'])}-visit {r['plan_type']} plan" if finished
                   else f"{int(r['visits_completed'])} of {int(r['prescribed_visits'])} visits done")
    elif r.get("lifetime_visit_count"):
        out.append(f"{int(r['lifetime_visit_count'])} visits in all")
    if r.get("days_since_visit") is not None:
        out.append(f"Last visit {_ago(int(r['days_since_visit']))}")
    if r.get("morning_share") is not None:
        out.append(f"Usually comes in the {'morning' if float(r['morning_share']) >= 0.5 else 'afternoon'}")
    if finished and r.get("referrals_made") is not None:
        n = int(r["referrals_made"])
        out.append("Hasn't referred anyone yet" if n == 0
                   else f"Has referred {n} {'person' if n == 1 else 'people'}")
    return out


def facts(row: dict) -> list[str]:
    """Short, plain facts about one lead or patient. Budget moves have none."""
    kind = row.get("target_type")
    return _lead(row) if kind == "lead" else _patient(row) if kind == "patient" else []


def action_facts(wh: Any, fq: str, run_id: str, location_id: str | None = None) -> dict[str, list[str]]:
    """Facts for every agent-written message in a run, or only one clinic's."""
    params = {"run_id": run_id}
    clinic_filter = ""
    if location_id:
        params["clinic_id"] = location_id
        clinic_filter = "AND location_id = :clinic_id"
    rows = wh.query(FACTS_SQL.format(fq=fq, clinic_filter=clinic_filter), params)
    return {r["action_id"]: facts(r) for r in rows}
