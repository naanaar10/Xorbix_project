"""Generator invariants: consistent columns, linked IDs, and the planted problems stay findable."""
from collections import Counter
from datetime import date

import pytest

from chiro_agent.datagen import (BEST_CLINIC, CAPACITY_CLINIC, COLUMNS, LEADS_CLINIC,
                                 RETENTION_CLINIC, SimConfig, simulate_network)


@pytest.fixture(scope="module")
def data():
    return simulate_network(SimConfig(as_of=date(2026, 10, 7), num_clinics=20, history_days=400))


def col(table, name):
    return COLUMNS[table].index(name)


def test_rows_match_declared_columns(data):
    for table, rows in data.items():
        assert rows, f"{table} is empty"
        assert {len(r) for r in rows} == {len(COLUMNS[table])}, table


def test_ids_link_up(data):
    patients = {r[0] for r in data["patients"]}
    appointments = {r[0] for r in data["appointments"]}
    plans = {r[0] for r in data["care_plans"]}
    assert all(r[col("visits", "appointment_id")] in appointments for r in data["visits"])
    assert all(r[col("visits", "patient_id")] in patients for r in data["visits"])
    assert all(r[col("care_plans", "patient_id")] in patients for r in data["care_plans"])
    converted = [r for r in data["leads"] if r[col("leads", "converted_flag")]]
    assert all(r[col("leads", "converted_patient_id")] in patients for r in converted)
    assert all(r[0] in plans for r in data["sim_ground_truth"])


def test_lifetime_visit_count_matches_visits(data):
    visits = Counter(r[col("visits", "patient_id")] for r in data["visits"])
    for p in data["patients"][:500]:
        assert p[col("patients", "lifetime_visit_count")] == visits[p[0]]


def _rate(rows, key_idx, pred):
    totals, hits = Counter(), Counter()
    for r in rows:
        totals[r[key_idx]] += 1
        hits[r[key_idx]] += pred(r)
    return {k: hits[k] / totals[k] for k in totals}


def test_planted_retention_problem_and_best_practice(data):
    closed = [r for r in data["care_plans"] if r[col("care_plans", "status")] in ("Completed", "Dropped")]
    completion = _rate(closed, col("care_plans", "location_id"),
                       lambda r: r[col("care_plans", "status")] == "Completed")
    assert min(completion, key=completion.get) == RETENTION_CLINIC
    assert max(completion, key=completion.get) == BEST_CLINIC


def test_planted_lead_problem(data):
    old = [r for r in data["leads"] if (date(2026, 10, 7) - r[col("leads", "created_date")]).days > 30]
    conversion = _rate(old, col("leads", "assigned_location_id"),
                       lambda r: r[col("leads", "converted_flag")])
    assert min(conversion, key=conversion.get) == LEADS_CLINIC


def test_planted_capacity_problem(data):
    past = [r for r in data["appointments"] if r[col("appointments", "status")] != "Scheduled"]
    no_show = _rate(past, col("appointments", "location_id"),
                    lambda r: r[col("appointments", "status")] == "No-Show")
    assert max(no_show, key=no_show.get) == CAPACITY_CLINIC


def test_deterministic():
    cfg = SimConfig(as_of=date(2026, 10, 7), num_clinics=3, history_days=60)
    a, b = simulate_network(cfg), simulate_network(cfg)
    assert a["visits"] == b["visits"]
