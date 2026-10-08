"""The math behind every dollar figure the app shows, as rows a person can check: what the number
is, its value, and how it was worked out. Built from the same values as the figure itself (the
clinic_kpis table, the bridge query, the impact summary), so the two can't drift apart. Figures
are rounded for reading; the app computes with the unrounded values."""
from __future__ import annotations

import math
from typing import Any

SLOTS_PER_DAYPART = 10
WEEKDAYS = 261
SHARE_OF_REMAINING_VISITS_KEPT = 0.7  # same as chiro_agent.measure
# Gaps smaller than these are normal clinic-to-clinic variation and price at $0 (src/sql/observe.sql).
TOLERANCE = {"completion": 0.03, "conversion": 0.02, "am": 0.10, "pm": 0.10, "no_show": 0.02}
# The fixes on the path to the goal, in order (BRIDGE_SQL in queries.py has a <key>_value for each).
BRIDGE_KEYS = ("leads", "capacity", "retention", "marketing", "membership", "referrals")
TITLES = {"retention": "Patients quit their care plan", "leads": "Slow lead replies", "capacity": "Empty chairs"}


def usd(x: Any) -> str:
    """Three significant figures: $1.14M, $927K, $70.4K, $450."""
    x = float(x or 0)
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= size * 0.9995:
            v = x / size
            digits = 2 if abs(v) < 10 else 1 if abs(v) < 100 else 0
            return f"${v:,.{digits}f}{suffix}"
    return f"${x:,.0f}"


def dollars(x: Any) -> str:
    return f"${float(x or 0):,.0f}"


def cents(x: Any) -> str:
    return f"${float(x or 0):,.2f}"


def pct1(x: Any) -> str:
    return f"{float(x or 0) * 100:.1f}%"


def pts(x: Any) -> str:
    return f"{round(float(x or 0) * 100, 1):g} points"


def count(x: Any) -> str:
    return f"{round(float(x or 0)):,}"


def num1(x: float) -> str:
    """A count that can be fractional, like 70% of 138 visits."""
    return count(x) if abs(x - round(x)) < 0.05 else f"{x:,.1f}"


def row(label: str, value: str, how: str = "") -> dict:
    return {"label": label, "value": value, "how": how}


def _gap(label: str, here: float, typical: float, tolerance: float, higher_is_better: bool = True) -> tuple[float, dict]:
    """How far worse than the typical clinic, beyond normal variation, and the row that says so."""
    worse_by = (typical - here) if higher_is_better else (here - typical)
    gap = max(0.0, worse_by - tolerance)
    if worse_by <= 0:
        how = f"{pct1(here)} here, better than the {pct1(typical)} typical clinic"
    elif gap == 0:
        how = f"{pct1(here)} here vs {pct1(typical)} at the typical clinic: a small difference we ignore (under {pts(tolerance)})"
    elif higher_is_better:
        how = f"{pct1(typical)} typical clinic − {pct1(here)} here − {pts(tolerance)} we ignore"
    else:
        how = f"{pct1(here)} here − {pct1(typical)} typical clinic − {pts(tolerance)} we ignore"
    return gap, row(f"{label} gap", pts(gap), how)


def _f(k: dict, key: str) -> float:
    return float(k.get(key) or 0)


def _retention(k: dict) -> dict:
    gap, gap_row = _gap("Plan completion", _f(k, "plan_completion_rate"), _f(k, "med_completion"),
                        TOLERANCE["completion"])
    value = _f(k, "retention_revenue_at_stake")
    rows = [gap_row]
    if gap > 0:
        plans = gap * _f(k, "closed_plans_per_year")
        rows += [row("Care plans not finished each year", count(plans),
                     f"{pct1(gap)} × {count(k.get('closed_plans_per_year'))} care plans that ended last year"),
                 row("Lost each year", usd(value), f"{count(plans)} × {dollars(k.get('value_of_a_completion'))} per finished care plan")]
    else:
        rows.append(row("Lost each year", usd(value)))
    return {"key": "retention", "title": TITLES["retention"], "value": value, "rows": rows}


def _leads(k: dict) -> dict:
    gap, gap_row = _gap("Lead conversion", _f(k, "lead_conversion_rate"), _f(k, "med_conversion"),
                        TOLERANCE["conversion"])
    value = _f(k, "leads_revenue_at_stake")
    rows = [gap_row]
    if gap > 0:
        patients = gap * _f(k, "leads_per_year")
        rows += [row("New patients missed each year", count(patients),
                     f"{pct1(gap)} × {count(k.get('leads_per_year'))} leads a year"),
                 row("Lost each year", usd(value), f"{count(patients)} × {dollars(k.get('revenue_per_patient'))} per new patient")]
    else:
        rows.append(row("Lost each year", usd(value)))
    return {"key": "leads", "title": TITLES["leads"], "value": value, "rows": rows}


def _capacity(k: dict) -> dict:
    am_gap, am_row = _gap("Mornings booked", _f(k, "am_utilization"), _f(k, "med_am_util"), TOLERANCE["am"])
    pm_gap, pm_row = _gap("Afternoons booked", _f(k, "pm_utilization"), _f(k, "med_pm_util"), TOLERANCE["pm"])
    ns_gap, ns_row = _gap("No-show", _f(k, "no_show_rate"), _f(k, "med_no_show"), TOLERANCE["no_show"],
                          higher_is_better=False)
    value = _f(k, "capacity_revenue_at_stake")
    terms = [(gap, base, what) for gap, base, what in (
        (am_gap, _f(k, "am_capacity"), "morning slots"),
        (pm_gap, _f(k, "pm_capacity"), "afternoon slots"),
        (ns_gap, _f(k, "appointments_per_year"), "appointments")) if gap > 0]
    rows = [am_row, pm_row, ns_row]
    note = None
    if terms:
        visits = sum(gap * base for gap, base, _ in terms)
        rows += [row("Visits lost each year", count(visits),
                     " + ".join(f"{pct1(gap)} × {count(base)} {what}" for gap, base, what in terms)),
                 row("Lost each year", usd(value), f"{count(visits)} × {cents(k.get('avg_visit_revenue'))} per visit")]
        slots = [(base, what) for gap, base, what in terms if what.endswith("slots")]
        per_chiro = SLOTS_PER_DAYPART * WEEKDAYS
        if len(slots) == 1:
            base = slots[0][0]
            note = (f"Slots a year: {count(base / per_chiro)} chiropractors × {SLOTS_PER_DAYPART} half-hour slots "
                    f"a morning or afternoon × {WEEKDAYS} weekdays = {count(base)}.")
        elif slots:
            note = (f"Slots a year: chiropractors working that part of the day × {SLOTS_PER_DAYPART} half-hour "
                    f"slots × {WEEKDAYS} weekdays ({count(_f(k, 'am_capacity') / per_chiro)} in the mornings, "
                    f"{count(_f(k, 'pm_capacity') / per_chiro)} in the afternoons).")
    else:
        rows.append(row("Lost each year", usd(value)))
    return {"key": "capacity", "title": TITLES["capacity"], "value": value, "rows": rows, "note": note}


def clinic_math(k: dict) -> dict:
    """One clinic's revenue at stake, problem by problem, biggest first, and the total."""
    levers = sorted([_retention(k), _leads(k), _capacity(k)], key=lambda part: -part["value"])
    total = row("Total lost each year", usd(k.get("total_revenue_at_stake")),
                " + ".join(f"{usd(part['value'])} {part['title'].lower()}" for part in levers))
    return {"levers": levers, "total": total}


def unit_math(k: dict) -> list[dict]:
    """Where the three dollar values come from (the same for every clinic)."""
    has_inputs = k.get("all_visits") is not None
    revenue = usd(k.get("all_visit_revenue"))
    return [
        row("Per new patient", dollars(k.get("revenue_per_patient")),
            f"{revenue} of revenue from visits ÷ {count(k.get('all_patients'))} patients" if has_inputs
            else "revenue from visits ÷ patients"),
        row("Per finished care plan", dollars(k.get("value_of_a_completion")),
            f"{dollars(k.get('completer_revenue'))} that a patient who finished a care plan spends in total − "
            f"{dollars(k.get('dropper_revenue'))} for one who quit early" if has_inputs
            else "what a patient who finished a care plan spends in total − one who quit early"),
        row("Per visit", cents(k.get("avg_visit_revenue")),
            f"{revenue} of revenue from visits ÷ {count(k.get('all_visits'))} visits" if has_inputs
            else "revenue from visits ÷ visits"),
    ]


def bridge_math(b: dict, revenue: float, clinic_count: int, goal: float) -> dict:
    """Each step on the path from today's revenue to the goal (BRIDGE_SQL in queries.py)."""
    leads_per_year, fast, today = _f(b, "leads_per_year"), _f(b, "conversion_within_hour"), _f(b, "conversion")
    extra_patients = leads_per_year * (fast - today)
    slots, booked = _f(b, "pm_capacity"), _f(b, "pm_booked")
    target = slots * 0.85
    plans, top, typical = _f(b, "closed_plans"), _f(b, "top_decile_completion"), _f(b, "median_completion")
    extra_plans = plans * (top - typical)
    values = [max(0.0, _f(b, f"{key}_value")) for key in BRIDGE_KEYS]
    fixes = sum(values)
    remainder = max(0.0, goal - revenue - fixes)
    per_clinic = revenue / clinic_count if clinic_count else 0.0
    new_clinics = math.ceil(remainder / per_clinic) if per_clinic else 0
    return {
        "leads": [
            row("Leads a year", count(leads_per_year), "all clinics: the last 11 months, stretched to a full year"),
            row("Conversion when a lead hears back within an hour", pct1(fast)),
            row("Conversion today", pct1(today)),
            row("Extra patients a year", count(extra_patients), f"({pct1(fast)} − {pct1(today)}) × {count(leads_per_year)} leads"),
            row("A year", usd(values[0]), f"{count(extra_patients)} × {dollars(b.get('revenue_per_patient'))} per new patient")],
        "capacity": [
            row("Afternoon slots a year", count(slots),
                f"each chiropractor who works afternoons × {SLOTS_PER_DAYPART} slots × {WEEKDAYS} weekdays"),
            row("Booked today", count(booked), f"{pct1(booked / slots if slots else 0)} of afternoon slots"),
            row("Booked at 85%", count(target), f"85% × {count(slots)}"),
            row("Extra visits a year", count(target - booked), f"{count(target)} − {count(booked)}"),
            row("A year", usd(values[1]), f"{count(target - booked)} × {cents(b.get('visit_revenue'))} per visit")],
        "retention": [
            row("Care plans that end each year", count(plans), "finished or quit early, all clinics"),
            row("Plan completion at the best 10% of clinics", pct1(top)),
            row("Plan completion at the typical clinic", pct1(typical)),
            row("Extra care plans finished each year", count(extra_plans), f"({pct1(top)} − {pct1(typical)}) × {count(plans)} care plans"),
            row("A year", usd(values[2]), f"{count(extra_plans)} × {dollars(b.get('completion_value'))} per finished care plan")],
        "marketing": _marketing_rows(b, values[3]),
        "membership": _membership_rows(b, values[4]),
        "referrals": _referral_rows(b, values[5]),
        "new_clinics": [
            row("Goal", usd(goal)),
            row("Revenue today", usd(revenue), f"revenue from visits in the last 12 months, {clinic_count} clinics"),
            row("From the fixes", usd(fixes), " + ".join(usd(v) for v in values)),
            row("Still to find", usd(remainder), f"{usd(goal)} − {usd(revenue)} − {usd(fixes)}"),
            row("Revenue of a typical clinic", usd(per_clinic), f"{usd(revenue)} ÷ {clinic_count} clinics"),
            row("New clinics", str(new_clinics), f"{usd(remainder)} ÷ {usd(per_clinic)}, rounded up")],
    }


def _marketing_rows(b: dict, value: float) -> list[dict]:
    costly, cheap = b.get("costly_channel") or "the most expensive channel", b.get("cheap_channel") or "the cheapest channel"
    costly_cpp = _f(b, "costly_spend") / _f(b, "costly_new_patients") if _f(b, "costly_new_patients") else 0.0
    cheap_cpp = _f(b, "cheap_spend") / _f(b, "cheap_new_patients") if _f(b, "cheap_new_patients") else 0.0
    moved = _f(b, "marketing_moved")
    lost = moved / costly_cpp if costly_cpp else 0.0
    won = moved / (2 * cheap_cpp) if cheap_cpp else 0.0
    return [
        row("Most expensive channel", costly, f"{dollars(costly_cpp)} per new patient: {usd(b.get('costly_spend'))} "
            f"spent last year ÷ {count(b.get('costly_new_patients'))} new patients"),
        row("Cheapest channel", cheap, f"{dollars(cheap_cpp)} per new patient: {usd(b.get('cheap_spend'))} ÷ "
            f"{count(b.get('cheap_new_patients'))} new patients"),
        row("Money moved each year", usd(moved),
            f"a quarter of {costly}'s budget, or what {cheap} spends now if that's less"),
        row(f"New patients lost from {costly}", count(lost), f"{usd(moved)} ÷ {dollars(costly_cpp)}"),
        row(f"New patients won through {cheap}", count(won),
            f"{usd(moved)} ÷ ({dollars(cheap_cpp)} × 2): moved money works half as well"),
        row("A year", usd(value), f"({count(won)} − {count(lost)}) × {dollars(b.get('revenue_per_patient'))} per new patient"),
    ]


def _finishers_row(b: dict) -> dict:
    return row("Patients who finish a care plan each year", count(b.get("finishers")), "all clinics, not counting Wellness plans")


def _membership_rows(b: dict, value: float) -> list[dict]:
    plan_value = _f(b, "wellness_visits") * _f(b, "visit_revenue")
    best = (f"the very best, {b['best_uptake_clinic']}, reaches {pct1(b.get('best_uptake'))}"
            if b.get("best_uptake_clinic") else "")
    return [
        _finishers_row(b),
        row("Start a Wellness plan at the best 10% of clinics", pct1(b.get("top_uptake")), best),
        row("Extra Wellness plans each year", count(b.get("extra_wellness_plans")),
            f"every clinic below {pct1(b.get('top_uptake'))} brought up to it"),
        row("Value of a Wellness plan", dollars(plan_value),
            f"{num1(_f(b, 'wellness_visits'))} visits × {cents(b.get('visit_revenue'))}"),
        row("A year", usd(value), f"{count(b.get('extra_wellness_plans'))} × {dollars(plan_value)}"),
    ]


def _referral_rows(b: dict, value: float) -> list[dict]:
    extra, per = _f(b, "extra_referrers"), _f(b, "referrals_per_referrer")
    return [
        _finishers_row(b),
        row("Refer someone at the best 10% of clinics", pct1(b.get("top_referral"))),
        row("Extra patients who refer someone each year", count(extra),
            f"every clinic below {pct1(b.get('top_referral'))} brought up to it"),
        row("People each of them refers", num1(per), "the average over every referral"),
        row("Referred people who become patients", pct1(b.get("referral_conversion"))),
        row("A year", usd(value), f"{count(extra)} × {num1(per)} × {pct1(b.get('referral_conversion'))} × "
            f"{dollars(b.get('revenue_per_patient'))} per new patient"),
    ]


def outcome_math(impact: list[dict], annual_dropouts: float, avg_visit_revenue: float) -> dict | None:
    """The three Results numbers: lift over doing nothing, revenue recovered, and the yearly projection
    (chiro_agent.measure.summarize)."""
    arms = {a["arm"]: a for a in impact}
    agent, holdout = arms.get("agent"), arms.get("holdout")
    if not agent or not holdout:
        return None
    lift = float(agent["lift_vs_holdout"] or 0)
    recovered = float(agent.get("recovered_revenue") or 0)
    visits_left = recovered / (SHARE_OF_REMAINING_VISITS_KEPT * avg_visit_revenue) if avg_visit_revenue else 0.0
    counted = visits_left * SHARE_OF_REMAINING_VISITS_KEPT
    returned_all = sum(a["patients_returned"] or 0 for a in impact)
    recovered_all = sum(float(a.get("recovered_revenue") or 0) for a in impact)
    per_return = recovered_all / returned_all if returned_all else 0.0
    extra = max(0.0, lift) * annual_dropouts
    return {
        "lift": [
            row("Came back after the agent's message", pct1(agent["return_rate"]),
                f"{agent['patients_returned']} of {agent['patients']} patients"),
            row("Came back with no message", pct1(holdout["return_rate"]),
                f"{holdout['patients_returned']} of {holdout['patients']} patients, the holdout group"),
            row("More patients came back", pts(lift), f"{pct1(agent['return_rate'])} − {pct1(holdout['return_rate'])}")],
        "recovered": [
            row("Patients who came back after the agent's message", str(agent["patients_returned"])),
            row("Visits left on their care plans", num1(visits_left),
                f"the visits those {agent['patients_returned']} patients still had to go"),
            row("Visits we count", num1(counted),
                f"{SHARE_OF_REMAINING_VISITS_KEPT:.0%} of {num1(visits_left)}: patients who come back don't all finish"),
            row("Money won back", usd(recovered), f"{num1(counted)} × {cents(avg_visit_revenue)} per visit")],
        "annualized": [
            row("More patients came back", pts(lift), "the agent's message vs no message, from above"),
            row("Patients who quit a care plan each year", count(annual_dropouts), "all clinics"),
            row("Extra patients back a year", count(extra),
                f"{pct1(lift)} × {count(annual_dropouts)}" if lift > 0
                else "no more patients came back than with no message, so none"),
            row("Value of a patient who comes back", dollars(per_return),
                f"{usd(recovered_all)} won back ÷ {returned_all} patients who came back (all groups)"),
            row("A year across the network", usd(agent["annualized_network_revenue"]),
                f"{count(extra)} × {dollars(per_return)}")],
    }
