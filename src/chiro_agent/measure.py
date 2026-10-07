"""Measure: simulate whether each retention patient came back, then compare arms.

Outreach isn't really sent, so outcomes are simulated. Each at-risk patient has a hidden true
reason for stopping (sim_ground_truth, which no agent tool can read). The chance they return
depends on whether the intervention fits that reason, so an agent that reads the signals well
beats a generic reminder, which beats doing nothing (the holdout arm).
"""
from __future__ import annotations

import random
from collections import defaultdict

from chiro_agent.context import now
from chiro_agent.db import Warehouse

# P(patient returns | true reason, intervention). Rows: true reason. Assumptions, stated openly.
RETURN_PROBABILITY = {
    #                       slot   call  member progress transport generic none
    "Feeling better":      (0.10, 0.20, 0.10,  0.32,    0.05,     0.08,   0.04),
    "Scheduling conflict": (0.45, 0.18, 0.06,  0.10,    0.08,     0.10,   0.05),
    "Cost/insurance":      (0.06, 0.12, 0.40,  0.10,    0.05,     0.06,   0.03),
    "Transportation":      (0.12, 0.10, 0.05,  0.06,    0.35,     0.05,   0.02),
    "Dissatisfied":        (0.08, 0.30, 0.05,  0.08,    0.04,     0.03,   0.02),
}
INTERVENTION_COLUMN = {
    "Specific slot offer": 0, "Provider call": 1, "Membership offer": 2, "Progress check-in": 3,
    "Transport or telehealth option": 4, "Generic reminder": 5, "None (holdout)": 6,
}
SHARE_OF_REMAINING_VISITS_KEPT = 0.7  # returning patients don't all finish the plan


def return_probability(true_reason: str | None, intervention: str) -> float:
    row = RETURN_PROBABILITY.get(true_reason or "Feeling better", RETURN_PROBABILITY["Feeling better"])
    return row[INTERVENTION_COLUMN.get(intervention, 5)]


def simulate_run(wh: Warehouse, fq: str, run_id: str) -> list[dict]:
    rows = wh.query(f"""
        SELECT a.action_id, a.location_id, a.target_id, a.arm, a.intervention, a.signal,
               g.true_reason, cp.prescribed_visits - cp.visits_completed AS remaining_visits,
               k.avg_visit_revenue
        FROM {fq}.action_queue a
        JOIN {fq}.care_plans cp ON a.care_plan_id = cp.care_plan_id
        LEFT JOIN {fq}.sim_ground_truth g ON a.care_plan_id = g.care_plan_id
        JOIN {fq}.clinic_kpis k ON a.location_id = k.location_id
        WHERE a.run_id = :run_id AND a.specialist = 'retention' AND a.status <> 'Rejected'""",
                    {"run_id": run_id})
    outcomes = []
    for r in rows:
        rng = random.Random(f"{run_id}|{r['target_id']}")
        returned = rng.random() < return_probability(r["true_reason"], r["intervention"])
        recovered = (r["remaining_visits"] * SHARE_OF_REMAINING_VISITS_KEPT * r["avg_visit_revenue"]
                     if returned else 0.0)
        outcomes.append({"action_id": r["action_id"], "run_id": run_id, "location_id": r["location_id"],
                         "target_id": r["target_id"], "arm": r["arm"], "intervention": r["intervention"],
                         "signal": r["signal"], "returned": returned,
                         "recovered_revenue": round(recovered, 2), "simulated_at": now()})
    return outcomes


def summarize(outcomes: list[dict], annual_dropouts: float, run_id: str) -> list[dict]:
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for o in outcomes:
        by_arm[o["arm"]].append(o)
    rate = {arm: sum(o["returned"] for o in rows) / len(rows) for arm, rows in by_arm.items()}
    returned = [o for o in outcomes if o["returned"]]
    value_per_return = (sum(o["recovered_revenue"] for o in returned) / len(returned)) if returned else 0.0
    holdout_rate = rate.get("holdout", 0.0)
    summary = []
    for arm in ("agent", "generic", "holdout"):
        if arm not in by_arm:
            continue
        lift = rate[arm] - holdout_rate
        summary.append({
            "run_id": run_id, "arm": arm, "patients": len(by_arm[arm]),
            "patients_returned": sum(o["returned"] for o in by_arm[arm]),
            "return_rate": round(rate[arm], 4),
            "recovered_revenue": round(sum(o["recovered_revenue"] for o in by_arm[arm]), 2),
            "lift_vs_holdout": round(lift, 4),
            # If every silent dropout in the network got this arm's treatment for a year:
            "annualized_network_revenue": round(max(0.0, lift) * annual_dropouts * value_per_return, 2),
            "simulated_at": now()})
    return summary


def measure_unmeasured_runs(wh: Warehouse, fq: str) -> list[dict]:
    """Simulate outcomes for every run that has retention actions but no impact summary yet."""
    runs = [r["run_id"] for r in wh.query(f"""
        SELECT DISTINCT a.run_id FROM {fq}.action_queue a
        LEFT ANTI JOIN {fq}.impact_summary s ON a.run_id = s.run_id
        WHERE a.specialist = 'retention'""")]
    annual_dropouts = wh.query(f"""
        SELECT COUNT(*) AS n FROM {fq}.care_plans cp CROSS JOIN {fq}.network_metadata m
        WHERE cp.status = 'Dropped' AND cp.last_visit_date > date_sub(m.as_of, 365)""")[0]["n"]
    results = []
    for run_id in runs:
        outcomes = simulate_run(wh, fq, run_id)
        if not outcomes:
            continue
        summary = summarize(outcomes, annual_dropouts, run_id)
        wh.insert(f"{fq}.action_outcomes", outcomes, batch=8)
        wh.insert(f"{fq}.impact_summary", summary)
        results.extend(summary)
    return results
